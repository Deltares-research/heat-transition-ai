"""Ingest a blob-hosted document corpus into the knowledge graph.

For each document: fetch from blob storage, extract markdown, translate to
English, chunk both renderings, embed every chunk, and write the lot in a
single transaction.

Each document commits on its own, so an interrupted run keeps everything it
finished and resumes from there. Documents already present in report_nodes are
skipped unless `force` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from src.blob.blob_client import BlobStore
from src.db.db_client import DBClient
from src.embedding.embedder import Embedder
from src.text.processing import Chunk, chunk_markdown, pdf_to_markdown, translate_markdown

__all__ = ["DocumentResult", "IngestReport", "ingest_documents", "list_documents"]

SUPPORTED = {".pdf", ".md"}
LANGUAGES = ("nl", "en")


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


def list_documents(store: BlobStore, prefix: str = "") -> list[str]:
    """Supported document blobs under a prefix, in a stable order."""
    return sorted(
        name for name in store.list(prefix)
        if Path(name).suffix.lower() in SUPPORTED
    )


def existing_doc_ids(client: DBClient) -> set[str]:
    return {row["doc_id"] for row in client.fetch("SELECT doc_id FROM report_nodes")}


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
) -> IngestReport:
    """Process every blob, committing each document independently.

    `on_progress(doc_id, stage)` is called as each document moves through
    fetch, translate, chunk, embed and write.
    """
    report = IngestReport()
    known = set() if force else existing_doc_ids(client)

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

    return report
