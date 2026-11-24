"""Rich-based command-line interface for the heat-transition-ai pipeline.

    python -m src.cli ingest-gemeentes
    python -m src.cli ingest-documents --prefix corpus/ --limit 5

Each command is a thin presentation layer over the same `src/ingestion/*`
functions the plain `pipeline/*.py` scripts call — this package only decides
how to show the work, never what the work is.
"""
