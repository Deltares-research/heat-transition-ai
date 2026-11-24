"""Step 02 - ingest, chunk and embed every document in the blob corpus.

For each document: fetch from Azure Blob Storage, extract markdown, translate
Dutch to English, chunk both renderings, embed every chunk with
text-embedding-3-large via Azure AI Foundry, and store the result.

Each document is committed on its own, so an interrupted run keeps what it
finished. By default documents already in the database are skipped; --force
reprocesses everything, replacing existing chunks.

Credentials: secrets/blob.env, secrets/embedder.env, secrets/db.env.

    python pipeline/02_ingest_documents.py
    python pipeline/02_ingest_documents.py --prefix corpus/ --limit 5
    python pipeline/02_ingest_documents.py --force
    python pipeline/02_ingest_documents.py --dry-run
"""

from __future__ import annotations

from _step import database, report, run, step_parser, summarise
from tqdm import tqdm

from src.blob.blob_client import BlobStore
from src.embedding.embedder import Embedder, EmbeddingConfig
from src.ingestion.documents import (
    existing_doc_ids,
    doc_id_for,
    ingest_documents,
    list_documents,
)

TABLES = ["report_nodes", "chunk_nodes", "chunk_report_edges"]

STAGES = {
    "fetch": "fetching",
    "translate": "translating",
    "chunk": "chunking",
    "embed": "embedding",
    "write": "writing",
    "skipped": "skipped",
    "done": "done",
}


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
    args = parser.parse_args()

    store = BlobStore(container=args.container)
    print(f"blob       {store.account} / {store.container_name}")

    blobs = list_documents(store, args.prefix)
    if not blobs:
        print(f"\nNo .pdf or .md blobs found under {args.prefix or '(container root)'}")
        return 1

    # Distinct documents share a doc_id if their filenames collide; that would
    # silently overwrite one with the other, so refuse rather than guess.
    seen: dict[str, str] = {}
    clashes = []
    for name in blobs:
        doc_id = doc_id_for(name)
        if doc_id in seen:
            clashes.append(f"{seen[doc_id]} and {name} both map to '{doc_id}'")
        seen[doc_id] = name
    if clashes:
        print("\nDuplicate document ids:")
        for clash in clashes:
            print(f"  {clash}")
        return 1

    config = EmbeddingConfig()
    print(f"embedder   {config.describe()}")

    with database() as client:
        known = set() if args.force else existing_doc_ids(client)
        todo = [b for b in blobs if args.force or doc_id_for(b) not in known]
        if args.limit:
            todo = todo[: args.limit]

        print(f"\nfound      {len(blobs)} documents")
        print(f"in db      {sum(doc_id_for(b) in known for b in blobs)}")
        print(f"to process {len(todo)}"
              + ("  (--force: existing chunks will be replaced)" if args.force else ""))
        print(f"languages  {'nl' if args.no_translate else 'nl + en'}")

        if args.dry_run:
            for name in todo[:20]:
                print(f"  would process {name}")
            if len(todo) > 20:
                print(f"  ... and {len(todo) - 20} more")
            print("\ndry run: nothing written")
            return 0

        if not todo:
            print("\nNothing to do. Use --force to reprocess.")
            return 0

        before = summarise(client, TABLES)
        embedder = Embedder(config)

        bar = tqdm(total=len(todo), unit="doc", desc="ingesting")

        def on_progress(doc_id: str, stage: str) -> None:
            if stage == "done":
                bar.update(1)
            else:
                bar.set_postfix_str(f"{STAGES.get(stage, stage)} {doc_id[:38]}")

        try:
            result = ingest_documents(
                client,
                store,
                todo,
                embedder,
                translate=not args.no_translate,
                force=args.force,
                on_progress=on_progress,
            )
        finally:
            bar.close()
            store.close()

        after = summarise(client, TABLES)

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
