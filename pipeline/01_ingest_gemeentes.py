"""Step 01 - load CBS gemeente, wijk and buurt data into the knowledge graph.

Reads the two CBS extracts in data/cbs/ and upserts them as nodes and edges.
Statistics are stored at buurt level only; wijk and gemeente figures are then
derived by refresh_cbs_aggregates(), so the three levels can never disagree.

Idempotent: every insert is an UPSERT and nodes absent from the input are
pruned, so re-running converges on exactly what the files describe.

    python pipeline/01_ingest_gemeentes.py
    python pipeline/01_ingest_gemeentes.py --buurten other.jsonl
"""

from __future__ import annotations

from _step import DATA, database, report, require_file, run, step_parser, summarise

from src.ingestion.gemeentes import ingest_gemeentes

DEFAULT_BUURTEN = DATA / "cbs" / "buurt_data.jsonl"
DEFAULT_GEMEENTEN = DATA / "cbs" / "gemeente_data.jsonl"

TABLES = [
    "gemeente_nodes",
    "wijk_nodes",
    "buurt_nodes",
    "wijk_gemeente_edges",
    "buurt_wijk_edges",
]


def step() -> int:
    parser = step_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--buurten",
        default=DEFAULT_BUURTEN,
        help="CBS buurt JSONL: one record per buurt, carrying all statistics",
    )
    parser.add_argument(
        "--gemeenten",
        default=DEFAULT_GEMEENTEN,
        help="CBS gemeente JSONL: the reference list of municipalities",
    )
    args = parser.parse_args()

    buurten = require_file(args.buurten)
    gemeenten = require_file(args.gemeenten)

    print(f"buurten    {buurten}")
    print(f"gemeenten  {gemeenten}\n")

    with database() as client:
        before = summarise(client, TABLES)
        ingest_gemeentes(client, buurten, gemeenten)
        after = summarise(client, TABLES)

    report(before, after)

    if after["buurt_nodes"] == 0:
        print("\nNothing was loaded - check the input files.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(step))
