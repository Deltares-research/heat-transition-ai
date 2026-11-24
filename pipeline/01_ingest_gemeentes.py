"""Step 01 - load CBS gemeente, wijk and buurt data into the knowledge graph.

Reads the two CBS extracts in data/cbs/ and upserts them as nodes and edges.
Statistics are stored at buurt level only; wijk and gemeente figures are then
derived by refresh_cbs_aggregates(), so the three levels can never disagree.

Idempotent: every insert is an UPSERT and nodes absent from the input are
pruned, so re-running converges on exactly what the files describe.

All the logic lives in src/ingestion/gemeentes.py — this script is just the
plain-text presentation of it. The same logic also drives
`python -m src.cli ingest-gemeentes`, the Rich CLI.

    python pipeline/01_ingest_gemeentes.py
    python pipeline/01_ingest_gemeentes.py --buurten other.jsonl
"""

from __future__ import annotations

from _step import report, require_file, run, step_parser

from src.db.db_client import DBClient
from src.ingestion.gemeentes import (
    DEFAULT_BUURT_PATH,
    DEFAULT_GEMEENTE_PATH,
    run_gemeente_ingest,
)


def step() -> int:
    parser = step_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--buurten",
        default=DEFAULT_BUURT_PATH,
        help="CBS buurt JSONL: one record per buurt, carrying all statistics",
    )
    parser.add_argument(
        "--gemeenten",
        default=DEFAULT_GEMEENTE_PATH,
        help="CBS gemeente JSONL: the reference list of municipalities",
    )
    args = parser.parse_args()

    buurten = require_file(args.buurten)
    gemeenten = require_file(args.gemeenten)

    print(f"buurten    {buurten}")
    print(f"gemeenten  {gemeenten}\n")

    with DBClient() as client:
        result = run_gemeente_ingest(client, buurten, gemeenten)

    report(result.before, result.after)

    if not result.loaded:
        print("\nNothing was loaded - check the input files.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(step))
