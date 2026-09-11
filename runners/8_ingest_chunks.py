from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from src.db.db_client import DBClient
from src.ingestion.chunks import ingest_chunks


DEFAULT_CHUNKS_PATH = ROOT / "data/processed/chunks_embedded.jsonl"
DEFAULT_ANSWERS_PATH = ROOT / "data/processed/chunk_answers.jsonl"
DEFAULT_MUNICIPALITIES_PATH = ROOT / "data/cbs/gemeente_data.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest reports, embedded chunks, and chunk answers into PostgreSQL.",
    )
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS_PATH)
    parser.add_argument(
        "--municipalities",
        type=Path,
        default=DEFAULT_MUNICIPALITIES_PATH,
    )
    return parser.parse_args()


def require_file(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"Input file not found: {path}")
    return path


def main() -> None:
    args = parse_args()
    client = DBClient()
    try:
        counts = ingest_chunks(
            client,
            require_file(args.chunks),
            require_file(args.answers),
            require_file(args.municipalities),
        )
    finally:
        client.close()

    print(
        "Chunk ingestion complete: "
        f"{counts['reports']} reports, "
        f"{counts['chunks']} chunks, "
        f"{counts['answers']} answers, "
        f"{counts['areas']} areas."
    )


if __name__ == "__main__":
    main()