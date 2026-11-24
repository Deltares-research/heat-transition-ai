"""`ingest-gemeentes` - load CBS gemeente, wijk and buurt data into the graph.

Same logic as `pipeline/01_ingest_gemeentes.py`, rendered with Rich instead of
plain text: a spinner tracking each load phase, then a table of the row-count
change per table.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.cli._render import render_table_diff
from src.db.db_client import DBClient
from src.ingestion.gemeentes import (
    DEFAULT_BUURT_PATH,
    DEFAULT_GEMEENTE_PATH,
    run_gemeente_ingest,
)
from src.paths import require_file

__all__ = ["add_parser", "run"]


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ingest-gemeentes",
        help="Load CBS gemeente, wijk and buurt data into the knowledge graph.",
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace, console: Console) -> int:
    buurten = require_file(args.buurten)
    gemeenten = require_file(args.gemeenten)

    console.print(f"[bold]buurten[/bold]    {buurten}")
    console.print(f"[bold]gemeenten[/bold]  {gemeenten}\n")

    with DBClient() as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Ingesting CBS data...", total=None)

            def on_stage(label: str, n: int | None) -> None:
                progress.update(task, description=f"{label} ({n:,})" if n else label)

            result = run_gemeente_ingest(client, buurten, gemeenten, on_stage=on_stage)

    render_table_diff(console, result.before, result.after, title="Gemeente ingest")

    if not result.loaded:
        console.print("\n[red]Nothing was loaded - check the input files.[/red]")
        return 1
    return 0
