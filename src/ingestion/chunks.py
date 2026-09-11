from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from tqdm import tqdm

from src.db.db_client import DBClient


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
    areas: set[str] = set()

    try:
        for doc_id, municipality in municipalities.items():
            client.insert(
                client.inserts["insert_gemeente_reference"]["query"],
                (
                    municipality["gemeente"],
                    municipality["gemeentecode"],
                    municipality.get("DimensionGroupId"),
                    municipality.get("peiljaar"),
                ),
            )
            client.insert(
                client.inserts["insert_report_node"]["query"],
                (doc_id, municipality["gemeente"], "en"),
            )
            client.insert(
                client.inserts["insert_report_gemeente_edge"]["query"],
                (doc_id, municipality["gemeentecode"]),
            )

        for (doc_id, index), chunk in tqdm(chunks.items(), desc="Ingesting chunks"):
            identifier = chunk_id(doc_id, index)
            embedding = chunk.get("embedding")
            client.insert(
                client.inserts["insert_chunk_node"]["query"],
                (
                    identifier,
                    index,
                    chunk.get("heading_path"),
                    chunk["text"],
                    chunk.get("char_start"),
                    chunk.get("char_end"),
                    chunk.get("n_chars", len(chunk["text"])),
                    embedding,
                    len(embedding) if embedding is not None else None,
                ),
            )
            client.insert(
                client.inserts["insert_chunk_report_edge"]["query"],
                (identifier, doc_id),
            )
            client.insert(
                client.inserts["insert_chunk_gemeente_edge"]["query"],
                (identifier, municipalities[doc_id]["gemeentecode"]),
            )

        for (doc_id, index, concept_id), answer in tqdm(
            answers.items(), desc="Ingesting chunk answers"
        ):
            chunk_identifier = chunk_id(doc_id, index)
            answer_identifier = answer_id(doc_id, index, concept_id)
            client.insert(
                client.inserts["insert_chunk_answer_node"]["query"],
                (
                    answer_identifier,
                    concept_id,
                    answer["question"],
                    answer["answer"],
                    answer.get("section"),
                ),
            )
            client.insert(
                client.inserts["insert_answer_chunk_edge"]["query"],
                (answer_identifier, chunk_identifier),
            )
            for area in answer.get("areas", []):
                area_type = area.get("type", "gebied").lower()
                if area_type not in {"buurt", "wijk", "gebied"}:
                    area_type = "gebied"
                area_identifier = area_id(doc_id, area["name"], area_type)
                areas.add(area_identifier)
                client.insert(
                    client.inserts["insert_area_node"]["query"],
                    (area_identifier, area["name"], area_type),
                )
                client.insert(
                    client.inserts["insert_chunk_area_edge"]["query"],
                    (chunk_identifier, area_identifier),
                )

        client.conn.commit()
    except Exception:
        client.conn.rollback()
        raise

    return {
        "reports": len(municipalities),
        "chunks": len(chunks),
        "answers": len(answers),
        "areas": len(areas),
    }