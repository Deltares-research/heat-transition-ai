"""Ingest a blob-hosted document corpus into the knowledge graph.

For each document: fetch from blob storage, extract markdown, translate to
English, chunk both renderings, embed every chunk, and write the lot in a
single transaction.

Each document commits on its own, so an interrupted run keeps everything it
finished and resumes from there. Documents already present in report_nodes are
skipped unless `force` is set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from src.blob import BlobStore
from src.db import DBClient
from src.embedding import Embedder
from src.text import Chunk, chunk_markdown, pdf_to_markdown, translate_markdown

__all__ = [
    "DEFAULT_LOG_PATH",
    "DOCUMENT_TABLES",
    "STAGE_LABELS",
    "DocumentPlan",
    "DocumentResult",
    "IngestReport",
    "find_id_clashes",
    "ingest_documents",
    "list_documents",
    "log_result",
    "plan_document_ingest",
]

SUPPORTED = {".pdf", ".md"}
LANGUAGES = ("nl", "en")

DOCUMENT_TABLES = ["report_nodes", "chunk_nodes", "chunk_report_edges"]

ROOT = Path(__file__).parents[2]
DEFAULT_LOG_PATH = ROOT / "logs" / "ingest_documents.jsonl"

# Human-readable label per stage key, for anything rendering ingest_documents'
# on_progress callback — the plain pipeline step and the Rich CLI both use
# these, styled differently.
STAGE_LABELS = {
    "fetch": "fetching",
    "translate": "translating",
    "chunk": "chunking",
    "embed": "embedding",
    "write": "writing",
    "skipped": "skipped",
    "done": "done",
}


def doc_id_for(blob_name: str) -> str:
    """corpus/municipality-plan-zwolle.pdf -> municipality-plan-zwolle."""
    return Path(blob_name).stem


def chunk_id_for(doc_id: str, language: str, index: int) -> str:
    return f"{doc_id}:{language}:{index}"


@dataclass
class DocumentResult:
    doc_id: str
    blob: str
    chunks: int = 0
    embedded: int = 0
    skipped: bool = False
    error: str | None = None


@dataclass
class IngestReport:
    results: list[DocumentResult] = field(default_factory=list)

    @property
    def ingested(self) -> list[DocumentResult]:
        return [r for r in self.results if not r.skipped and not r.error]

    @property
    def skipped(self) -> list[DocumentResult]:
        return [r for r in self.results if r.skipped]

    @property
    def failed(self) -> list[DocumentResult]:
        return [r for r in self.results if r.error]

    @property
    def total_chunks(self) -> int:
        return sum(r.chunks for r in self.results)


def log_result(result: DocumentResult, log_path: Path | str = DEFAULT_LOG_PATH) -> None:
    """Append one line recording a document's outcome to a local audit log.

    One JSON object per line: doc_id, blob, the UTC timestamp the document was
    processed, a status (success/failed/skipped), chunk count and error if
    any. Appending per document (rather than batching) keeps the log
    consistent with an interrupted run, which also stops partway through.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status = "skipped" if result.skipped else ("failed" if result.error else "success")
    record = {
        "doc_id": result.doc_id,
        "blob": result.blob,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "chunks": result.chunks,
        "error": result.error,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_documents(store: BlobStore, prefix: str = "") -> list[str]:
    """Supported document blobs under a prefix, in a stable order."""
    return sorted(
        name for name in store.list(prefix)
        if Path(name).suffix.lower() in SUPPORTED
    )


def existing_doc_ids(client: DBClient) -> set[str]:
    return {row["doc_id"] for row in client.fetch("SELECT doc_id FROM report_nodes")}


def find_id_clashes(blobs: Iterable[str]) -> list[str]:
    """Human-readable descriptions of blob names that collide on doc_id.

    Distinct documents share a doc_id if their filenames collide, which would
    silently overwrite one with the other — callers should refuse to proceed
    rather than guess which one wins.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for name in blobs:
        doc_id = doc_id_for(name)
        if doc_id in seen:
            clashes.append(f"{seen[doc_id]} and {name} both map to '{doc_id}'")
        else:
            seen[doc_id] = name
    return clashes


@dataclass
class DocumentPlan:
    """What a document-ingest run would do, before any writing happens."""

    blobs: list[str]
    known_ids: set[str]
    todo: list[str]
    clashes: list[str]

    @property
    def in_db(self) -> int:
        return sum(1 for b in self.blobs if doc_id_for(b) in self.known_ids)


def plan_document_ingest(
    client: DBClient,
    store: BlobStore,
    prefix: str = "",
    force: bool = False,
    limit: int = 0,
    blobs: list[str] | None = None,
) -> DocumentPlan:
    """List blobs, flag doc_id clashes, and work out what still needs ingesting.

    Pass `blobs` if the caller already listed the container (e.g. to check for
    clashes before opening a database connection) — avoids listing twice.
    """
    if blobs is None:
        blobs = list_documents(store, prefix)
    clashes = find_id_clashes(blobs)
    known = set() if force else existing_doc_ids(client)
    todo = [b for b in blobs if force or doc_id_for(b) not in known]
    if limit:
        todo = todo[:limit]
    return DocumentPlan(blobs=blobs, known_ids=known, todo=todo, clashes=clashes)


def _load_markdown(store: BlobStore, blob_name: str) -> str:
    data = store.download_bytes(blob_name)
    if Path(blob_name).suffix.lower() == ".md":
        return data.decode("utf-8", errors="replace")
    return pdf_to_markdown(data)


def _renderings(dutch: str, translate: bool) -> dict[str, str]:
    """The document in each language that should be stored."""
    texts = {"nl": dutch}
    if translate:
        texts["en"] = translate_markdown(dutch)
    return texts


def _write(
    client: DBClient,
    doc_id: str,
    blob_name: str,
    chunks_by_language: dict[str, list[Chunk]],
    vectors_by_language: dict[str, list[list[float]]],
    force: bool,
) -> int:
    """Persist one document and all its chunks in a single transaction."""
    with client.transaction():
        if force:
            client.insert(client.inserts["delete_report_chunks"]["query"], (doc_id,))

        client.insert(
            client.inserts["insert_report_node"]["query"],
            (doc_id, Path(blob_name).name, "nl"),
        )

        chunk_rows = []
        edge_rows = []
        for language, chunks in chunks_by_language.items():
            vectors = vectors_by_language[language]
            for chunk, vector in zip(chunks, vectors):
                identifier = chunk_id_for(doc_id, language, chunk.chunk_index)
                chunk_rows.append((
                    identifier,
                    chunk.chunk_index,
                    language,
                    chunk.heading_path,
                    chunk.text,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.n_chars,
                    vector,
                    len(vector),
                ))
                edge_rows.append((identifier, doc_id))

        client.insert_many(client.inserts["insert_chunk_node"]["query"], chunk_rows)
        client.insert_many(client.inserts["insert_chunk_report_edge"]["query"], edge_rows)

    return len(chunk_rows)


def ingest_documents(
    client: DBClient,
    store: BlobStore,
    blobs: Iterable[str],
    embedder: Embedder,
    translate: bool = True,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
    known_ids: set[str] | None = None,
    log_path: Path | str = DEFAULT_LOG_PATH,
) -> IngestReport:
    """Process every blob, committing each document independently.

    `on_progress(doc_id, stage)` is called as each document moves through
    fetch, translate, chunk, embed and write. Pass `known_ids` (e.g. from a
    `DocumentPlan`) to skip re-querying which documents already exist. Every
    document, including skipped ones, gets one line in `log_path` via
    `log_result`.
    """
    report = IngestReport()
    if force:
        known: set[str] = set()
    elif known_ids is not None:
        known = known_ids
    else:
        known = existing_doc_ids(client)

    def progress(doc_id: str, stage: str) -> None:
        if on_progress:
            on_progress(doc_id, stage)

    for blob_name in blobs:
        doc_id = doc_id_for(blob_name)
        result = DocumentResult(doc_id=doc_id, blob=blob_name)

        if doc_id in known:
            result.skipped = True
            report.results.append(result)
            progress(doc_id, "skipped")
            log_result(result, log_path)
            continue

        try:
            progress(doc_id, "fetch")
            dutch = _load_markdown(store, blob_name)
            if not dutch.strip():
                raise ValueError("no extractable text (scanned or image-only?)")

            progress(doc_id, "translate" if translate else "chunk")
            texts = _renderings(dutch, translate)

            progress(doc_id, "chunk")
            chunks_by_language = {
                language: chunk_markdown(text) for language, text in texts.items()
            }
            if not any(chunks_by_language.values()):
                raise ValueError("document produced no chunks above the minimum size")

            progress(doc_id, "embed")
            vectors_by_language = {
                language: embedder.embed([c.text for c in chunks])
                for language, chunks in chunks_by_language.items()
            }

            progress(doc_id, "write")
            result.chunks = _write(
                client, doc_id, blob_name,
                chunks_by_language, vectors_by_language, force,
            )
            result.embedded = result.chunks

        except Exception as exc:  # noqa: BLE001 - one bad document must not stop the run
            client.rollback()
            result.error = f"{type(exc).__name__}: {exc}"[:200]

        report.results.append(result)
        progress(doc_id, "done")
        log_result(result, log_path)

    return report
