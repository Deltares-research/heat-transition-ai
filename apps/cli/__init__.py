"""Rich-based command-line interface for the heat-transition-ai pipeline.

    python -m apps.cli ingest-gemeentes
    python -m apps.cli ingest-documents --prefix corpus/ --limit 5

Each command is a thin presentation layer over the same `src/ingestion/*`
functions the plain `pipeline/*.py` scripts call — this package only decides
how to show the work, never what the work is.
"""

from apps.cli.app import build_parser, main

__all__ = ["build_parser", "main"]
