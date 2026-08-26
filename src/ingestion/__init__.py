from src.ingestion.scrape_pdfs import download_pdfs
from src.ingestion.gemeentes import ingest_gemeentes
from src.ingestion.questions import ingest_questions

__all__ = [
    "download_pdfs",
    "ingest_gemeentes",
    "ingest_questions",
]