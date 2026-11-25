"""`ingest-documents` - ingest, chunk and embed the blob corpus.

Same logic as `pipeline/02_ingest_documents.py`, rendered with Rich instead
of plain text: a progress bar tracking fetch/translate/chunk/embed/write per
document, then a table of the row-count change per table.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from apps.cli._render import render_table_diff
from src.blob import BlobStore
from src.db import DBClient, table_counts
from src.embedding import Embedder, EmbeddingConfig
from src.ingestion import (
    DEFAULT_LOG_PATH,
    DOCUMENT_TABLES,
    STAGE_LABELS,
    DocumentPlan,
    find_id_clashes,
    ingest_documents,
    list_documents,
    plan_document_ingest,
)

__all__ = ["add_parser", "run"]


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ingest-documents",
        help="Ingest, chunk and embed every document in the blob corpus.",
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--prefix", default="", help="only blobs under this prefix")
    parser.add_argument("--container", default=None, help="override secrets/blob.env")
    parser.add_argument(
        "--force",
        action="store_true",
        help="reprocess every document, replacing chunks already stored",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="store Dutch only, skipping the English rendering",
    )
    parser.add_argument("--limit", type=int, default=0, help="process at most N documents")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be processed, then stop",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_PATH,
        help="JSONL audit log: one line per document, with date and success",
    )
    parser.set_defaults(handler=run)


def _render_plan(console: Console, plan: DocumentPlan, force: bool, translate: bool) -> None:
    console.print(f"\n[bold]found[/bold]       {len(plan.blobs)} documents")
    console.print(f"[bold]in db[/bold]       {plan.in_db}")
    suffix = (
        "  [yellow](--force: existing chunks will be replaced)[/yellow]" if force else ""
    )
    console.print(f"[bold]to process[/bold]  {len(plan.todo)}{suffix}")
    console.print(f"[bold]languages[/bold]   {'nl + en' if translate else 'nl'}")


def run(args: argparse.Namespace, console: Console) -> int:
    console.print(f"[bold]log[/bold]        {args.log_file}")
    store = BlobStore(container=args.container)
    console.print(f"[bold]blob[/bold]       {store.account} / {store.container_name}")

    blobs = list_documents(store, args.prefix)
    if not blobs:
        console.print(
            f"\n[red]No .pdf or .md blobs found under "
            f"{args.prefix or '(container root)'}[/red]"
        )
        return 1

    clashes = find_id_clashes(blobs)
    if clashes:
        console.print("\n[red]Duplicate document ids:[/red]")
        for clash in clashes:
            console.print(f"  {clash}")
        return 1

    config = EmbeddingConfig()
    console.print(f"[bold]embedder[/bold]   {config.describe()}")

    with DBClient() as client:
        plan = plan_document_ingest(
            client, store, prefix=args.prefix, force=args.force,
            limit=args.limit, blobs=blobs,
        )
        _render_plan(console, plan, args.force, not args.no_translate)

        if args.dry_run:
            for name in plan.todo[:20]:
                console.print(f"  would process {name}")
            if len(plan.todo) > 20:
                console.print(f"  ... and {len(plan.todo) - 20} more")
            console.print("\n[yellow]dry run: nothing written[/yellow]")
            return 0

        if not plan.todo:
            console.print("\nNothing to do. Use --force to reprocess.")
            return 0

        before = table_counts(client, DOCUMENT_TABLES)
        embedder = Embedder(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("ingesting", total=len(plan.todo))

            def on_progress(doc_id: str, stage: str) -> None:
                if stage == "done":
                    progress.advance(task)
                else:
                    label = STAGE_LABELS.get(stage, stage)
                    progress.update(task, description=f"{label} {doc_id[:38]}")

            try:
                result = ingest_documents(
                    client,
                    store,
                    plan.todo,
                    embedder,
                    translate=not args.no_translate,
                    force=args.force,
                    on_progress=on_progress,
                    known_ids=plan.known_ids,
                    log_path=args.log_file,
                )
            finally:
                store.close()

        after = table_counts(client, DOCUMENT_TABLES)

    console.print(
        f"\n[green]ingested[/green] {len(result.ingested)} documents, "
        f"{result.total_chunks:,} chunks ({config.dimensions}d embeddings)"
    )
    if result.skipped:
        console.print(f"skipped   {len(result.skipped)} already in the database")

    render_table_diff(console, before, after, title="Document ingest")

    if result.failed:
        console.print(f"\n[red]FAILED ({len(result.failed)}):[/red]")
        for item in result.failed:
            console.print(f"  {item.doc_id}: {item.error}")
        return 1
    return 0
