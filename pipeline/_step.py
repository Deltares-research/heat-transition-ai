"""Shared scaffolding for pipeline steps.

Every step is a standalone script that can be run directly::

    python pipeline/01_ingest_gemeentes.py --help

Steps import from here rather than repeating path setup, argument boilerplate
and connection lifecycle. Zero-padded step numbers (01_, 02_) mark the rebuilt
pipeline; single-digit ones are still the old runners awaiting a rewrite.
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import safe_console  # noqa: E402
from src.db.db_client import DBClient  # noqa: E402

DATA = ROOT / "data"

__all__ = [
    "DATA",
    "ROOT",
    "database",
    "require_file",
    "run",
    "step_parser",
    "summarise",
]


def step_parser(description: str) -> argparse.ArgumentParser:
    """An argument parser with the conventions every step shares."""
    return argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )


def require_file(path: Path | str) -> Path:
    """Resolve a required input, failing with a readable message."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise SystemExit(f"Input file not found: {resolved}")
    return resolved


@contextmanager
def database(readonly: bool = False, ensure_schema: bool = True) -> Iterator[DBClient]:
    """Open the graph database and always close it."""
    client = DBClient(readonly=readonly, ensure_schema=ensure_schema)
    try:
        yield client
    finally:
        client.close()


def summarise(client: DBClient, tables: list[str]) -> dict[str, int]:
    """Row count per table, for before/after reporting."""
    counts: dict[str, int] = {}
    present = {
        row["table_name"]
        for row in client.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    }
    for table in tables:
        if table in present:
            counts[table] = client.fetch_one(f"SELECT count(*) AS n FROM {table}")["n"]
        else:
            counts[table] = 0
    return counts


def report(before: dict[str, int], after: dict[str, int]) -> None:
    """Print row counts with the change this step made."""
    width = max(len(name) for name in after)
    print(f"\n  {'table'.ljust(width)}  {'rows':>10}  {'change':>9}")
    for table, count in after.items():
        delta = count - before.get(table, 0)
        marker = f"{delta:+,}" if delta else "-"
        print(f"  {table.ljust(width)}  {count:>10,}  {marker:>9}")


def run(step: Callable[[], int | None]) -> int:
    """Execute a step with console safety, timing and readable failures.

    Operational problems (missing config, unreachable server, absent input)
    print a single line. Anything else keeps its traceback, because an
    unexpected exception in a pipeline step is a bug worth seeing in full.
    """
    safe_console()
    started = time.perf_counter()
    try:
        code = step() or 0
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    except (ConnectionError, PermissionError, RuntimeError) as exc:
        print(f"\n{exc}")
        return 1
    print(f"\ndone in {time.perf_counter() - started:,.1f}s")
    return code
