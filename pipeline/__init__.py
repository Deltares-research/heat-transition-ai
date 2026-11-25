"""The heat-transition-ai pipeline: one standalone script per step.

Run a single step directly (``python pipeline/01_ingest_gemeentes.py``), or
every step in order with ``python -m pipeline`` (see ``pipeline/__main__.py``).
"""

STEPS = [
    "01_ingest_gemeentes.py",
    "02_ingest_documents.py",
]
