from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from src.db.db_client import DBClient
from src.ingestion.gemeentes import ingest_gemeentes


DEFAULT_BUURT_PATH = ROOT / "data/cbs/buurt_data.jsonl"
DEFAULT_GEMEENTE_PATH = ROOT / "data/cbs/gemeente_data.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest CBS gemeente, wijk, and buurt data into PostgreSQL.",
    )
    parser.add_argument(
        "--buurten",
        type=Path,
        default=DEFAULT_BUURT_PATH,
        help=f"Buurt JSONL file (default: {DEFAULT_BUURT_PATH})",
    )
    parser.add_argument(
        "--gemeenten",
        type=Path,
        default=DEFAULT_GEMEENTE_PATH,
        help=f"Gemeente JSONL file (default: {DEFAULT_GEMEENTE_PATH})",
    )
    return parser.parse_args()


def require_file(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"Input file not found: {path}")
    return path


def main() -> None:
    args = parse_args()
    buurt_path = require_file(args.buurten)
    gemeente_path = require_file(args.gemeenten)

    client = DBClient()
    try:
        ingest_gemeentes(client, buurt_path, gemeente_path)
        counts = client.fetch(
            """
            SELECT
                (SELECT count(*) FROM gemeente_nodes) AS gemeentes,
                (SELECT count(*) FROM wijk_nodes) AS wijken,
                (SELECT count(*) FROM buurt_nodes) AS buurten,
                (SELECT count(*) FROM wijk_gemeente_edges) AS wijk_edges,
                (SELECT count(*) FROM buurt_wijk_edges) AS buurt_edges
            """
        )[0]
    finally:
        client.close()

    print(
        "CBS ingestion complete: "
        f"{counts['gemeentes']} gemeentes, "
        f"{counts['wijken']} wijken, "
        f"{counts['buurten']} buurten, "
        f"{counts['wijk_edges']} wijk-gemeente edges, "
        f"{counts['buurt_edges']} buurt-wijk edges."
    )


if __name__ == "__main__":
    main()