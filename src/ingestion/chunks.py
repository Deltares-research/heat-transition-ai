from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from src.db import DBClient


def load_records(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array in {path}")
        return data
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def normalize_name(value: str) -> str:
    value = re.sub(r"\s*\(gemeente\)\s*$", "", value, flags=re.IGNORECASE)
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in value if character.isalnum())


def chunk_id(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}:{chunk_index}"


def answer_id(doc_id: str, chunk_index: int, concept_id: str) -> str:
    return f"{doc_id}:{chunk_index}:{concept_id}"


def area_id(doc_id: str, name: str, area_type: str) -> str:
    identity = f"{doc_id}\0{area_type}\0{normalize_name(name)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def municipality_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        index.setdefault(normalize_name(row["gemeente"]), []).append(row)
    return index


def resolve_municipalities(
    doc_ids: set[str],
    municipality_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index = municipality_index(municipality_rows)
    resolved = {}
    for doc_id in sorted(doc_ids):
        matches = index.get(normalize_name(doc_id), [])
        codes = {row["gemeentecode"] for row in matches}
        if not matches:
            raise ValueError(f"No CBS municipality matches doc_id {doc_id!r}")
        if len(codes) != 1:
            raise ValueError(
                f"Ambiguous CBS municipality for doc_id {doc_id!r}: {sorted(codes)}"
            )
        resolved[doc_id] = max(matches, key=lambda row: row.get("peiljaar") or 0)
    return resolved


def deduplicate(
    records: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    return {tuple(record[field] for field in key_fields): record for record in records}


def ingest_chunks(
    client: DBClient,
    chunks_path: Path | str,
    answers_path: Path | str,
    municipalities_path: Path | str,
) -> dict[str, int]:
    chunks = deduplicate(load_records(chunks_path), ("doc_id", "chunk_index"))
    answers = deduplicate(
        load_records(answers_path),
        ("doc_id", "chunk_index", "concept_id"),
    )
    missing_chunks = {
        (doc_id, chunk_index)
        for doc_id, chunk_index, _ in answers
        if (doc_id, chunk_index) not in chunks
    }
    if missing_chunks:
        sample = sorted(missing_chunks)[:5]
        raise ValueError(f"Answers refer to missing chunks: {sample}")

    municipality_rows = load_records(municipalities_path)
    municipalities = resolve_municipalities(
        {doc_id for doc_id, _ in chunks},
        municipality_rows,
    )
    # Build every row set first, then send each as one batch. A per-row loop
    # costs a network round trip per statement, which dominates the runtime
    # once the database is remote.
    reference_rows: dict[str, tuple[Any, ...]] = {}
    report_rows: list[tuple[Any, ...]] = []
    report_edge_rows: list[tuple[Any, ...]] = []

    for doc_id, municipality in municipalities.items():
        reference_rows[municipality["gemeentecode"]] = (
            municipality["gemeente"],
            municipality["gemeentecode"],
            municipality.get("DimensionGroupId"),
            municipality.get("peiljaar"),
        )
        report_rows.append((doc_id, municipality["gemeente"], "en"))
        report_edge_rows.append((doc_id, municipality["gemeentecode"]))

    chunk_rows: list[tuple[Any, ...]] = []
    chunk_report_rows: list[tuple[Any, ...]] = []
    chunk_gemeente_rows: list[tuple[Any, ...]] = []

    for (doc_id, index), chunk in chunks.items():
        identifier = chunk_id(doc_id, index)
        embedding = chunk.get("embedding")
        chunk_rows.append((
            identifier,
            index,
            chunk.get("language", "en"),  # this path reads data/corpus/mds_en
            chunk.get("heading_path"),
            chunk["text"],
            chunk.get("char_start"),
            chunk.get("char_end"),
            chunk.get("n_chars", len(chunk["text"])),
            embedding,
            len(embedding) if embedding is not None else None,
        ))
        chunk_report_rows.append((identifier, doc_id))
        chunk_gemeente_rows.append((identifier, municipalities[doc_id]["gemeentecode"]))

    answer_rows: list[tuple[Any, ...]] = []
    answer_edge_rows: list[tuple[Any, ...]] = []
    area_rows: dict[str, tuple[Any, ...]] = {}
    area_edge_rows: dict[tuple[str, str], tuple[str, str]] = {}

    for (doc_id, index, concept_id), answer in answers.items():
        chunk_identifier = chunk_id(doc_id, index)
        answer_identifier = answer_id(doc_id, index, concept_id)
        answer_rows.append((
            answer_identifier,
            concept_id,
            answer["question"],
            answer["answer"],
            answer.get("section"),
        ))
        answer_edge_rows.append((answer_identifier, chunk_identifier))

        for area in answer.get("areas", []):
            area_type = area.get("type", "gebied").lower()
            if area_type not in {"buurt", "wijk", "gebied"}:
                area_type = "gebied"
            area_identifier = area_id(doc_id, area["name"], area_type)
            area_rows[area_identifier] = (area_identifier, area["name"], area_type)
            area_edge_rows[(chunk_identifier, area_identifier)] = (
                chunk_identifier, area_identifier,
            )

    # Nodes before the edges that reference them.
    stages = [
        ("gemeente references", "insert_gemeente_reference", list(reference_rows.values())),
        ("reports", "insert_report_node", report_rows),
        ("report-gemeente edges", "insert_report_gemeente_edge", report_edge_rows),
        ("chunks", "insert_chunk_node", chunk_rows),
        ("chunk-report edges", "insert_chunk_report_edge", chunk_report_rows),
        ("chunk-gemeente edges", "insert_chunk_gemeente_edge", chunk_gemeente_rows),
        ("chunk answers", "insert_chunk_answer_node", answer_rows),
        ("answer-chunk edges", "insert_answer_chunk_edge", answer_edge_rows),
        ("areas", "insert_area_node", list(area_rows.values())),
        ("chunk-area edges", "insert_chunk_area_edge", list(area_edge_rows.values())),
    ]

    print("Ingesting chunks")
    with client.transaction():
        for label, statement, rows in stages:
            print(f"  {label:<22} {len(rows):>8,}", flush=True)
            client.insert_many(client.inserts[statement]["query"], rows)

    return {
        "reports": len(municipalities),
        "chunks": len(chunks),
        "answers": len(answers),
        "areas": len(area_rows),
    }