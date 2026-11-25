"""Shared scaffolding for pipeline steps.

Every step is a standalone script that can be run directly::

    python pipeline/01_ingest_gemeentes.py --help

This module holds only script plumbing — argument-parsing conventions, a
timing/error wrapper, a plain-text row-count diff printer, and a re-export of
`require_file`. The actual ingestion logic lives in `src/`, importable by
both these scripts and `apps/cli/` (the Rich CLI), so the two presentations
never diverge on what a step actually does.

Zero-padded step numbers (01_, 02_) mark the rebuilt pipeline; single-digit
ones are still the old runners awaiting a rewrite.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import safe_console  # noqa: E402
from src.paths import require_file  # noqa: E402

DATA = ROOT / "data"

__all__ = [
    "DATA",
    "ROOT",
    "report",
    "require_file",
    "run",
    "step_parser",
]


def step_parser(description: str) -> argparse.ArgumentParser:
    """An argument parser with the conventions every step shares."""
    return argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )


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
    except (ConnectionError, PermissionError, RuntimeError, FileNotFoundError) as exc:
        print(f"\n{exc}")
        return 1
    print(f"\ndone in {time.perf_counter() - started:,.1f}s")
    return code
