"""Step 02 - ingest, chunk and embed every document in the blob corpus.

For each document: fetch from Azure Blob Storage, extract markdown, translate
Dutch to English, chunk both renderings, embed every chunk with
text-embedding-3-large via Azure AI Foundry, and store the result.

Each document is committed on its own, so an interrupted run keeps what it
finished. By default documents already in the database are skipped; --force
reprocesses everything, replacing existing chunks.

All the logic lives in src/ingestion/documents.py — this script is just the
plain-text presentation of it. The same logic also drives
`python -m apps.cli ingest-documents`, the Rich CLI.

Credentials: secrets/blob.env, secrets/embedder.env, secrets/db.env.

    python pipeline/02_ingest_documents.py
    python pipeline/02_ingest_documents.py --prefix corpus/ --limit 5
    python pipeline/02_ingest_documents.py --force
    python pipeline/02_ingest_documents.py --dry-run
"""

from __future__ import annotations

from _step import report, run, step_parser
from tqdm import tqdm

from src.blob import BlobStore
from src.db import DBClient, table_counts
from src.embedding import Embedder, EmbeddingConfig
from src.ingestion import (
    DEFAULT_LOG_PATH,
    DOCUMENT_TABLES,
    STAGE_LABELS,
    find_id_clashes,
    ingest_documents,
    list_documents,
    plan_document_ingest,
)


def step() -> int:
    parser = step_parser(__doc__.splitlines()[0])
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
    args = parser.parse_args()

    print(f"log        {args.log_file}")
    store = BlobStore(container=args.container)
    print(f"blob       {store.account} / {store.container_name}")

    blobs = list_documents(store, args.prefix)
    if not blobs:
        print(f"\nNo .pdf or .md blobs found under {args.prefix or '(container root)'}")
        return 1

    clashes = find_id_clashes(blobs)
    if clashes:
        print("\nDuplicate document ids:")
        for clash in clashes:
            print(f"  {clash}")
        return 1

    config = EmbeddingConfig()
    print(f"embedder   {config.describe()}")

    with DBClient() as client:
        plan = plan_document_ingest(
            client, store, prefix=args.prefix, force=args.force,
            limit=args.limit, blobs=blobs,
        )

        print(f"\nfound      {len(plan.blobs)} documents")
        print(f"in db      {plan.in_db}")
        print(f"to process {len(plan.todo)}"
              + ("  (--force: existing chunks will be replaced)" if args.force else ""))
        print(f"languages  {'nl' if args.no_translate else 'nl + en'}")

        if args.dry_run:
            for name in plan.todo[:20]:
                print(f"  would process {name}")
            if len(plan.todo) > 20:
                print(f"  ... and {len(plan.todo) - 20} more")
            print("\ndry run: nothing written")
            return 0

        if not plan.todo:
            print("\nNothing to do. Use --force to reprocess.")
            return 0

        before = table_counts(client, DOCUMENT_TABLES)
        embedder = Embedder(config)

        bar = tqdm(total=len(plan.todo), unit="doc", desc="ingesting")

        def on_progress(doc_id: str, stage: str) -> None:
            if stage == "done":
                bar.update(1)
            else:
                bar.set_postfix_str(f"{STAGE_LABELS.get(stage, stage)} {doc_id[:38]}")

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
            bar.close()
            store.close()

        after = table_counts(client, DOCUMENT_TABLES)

    print(f"\ningested {len(result.ingested)} documents, "
          f"{result.total_chunks:,} chunks "
          f"({config.dimensions}d embeddings)")
    if result.skipped:
        print(f"skipped  {len(result.skipped)} already in the database")

    report(before, after)

    if result.failed:
        print(f"\nFAILED ({len(result.failed)}):")
        for item in result.failed:
            print(f"  {item.doc_id}: {item.error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(step))
