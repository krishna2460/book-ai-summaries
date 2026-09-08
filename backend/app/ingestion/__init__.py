"""
Ingestion sub-package — public API.

Other modules should import from here:
    from app.ingestion import ingest_file, TextChunk, count_tokens
"""

from app.ingestion.chunker import TextChunk, count_tokens
from app.ingestion.pipeline import ingest_file, get_page_count, SUPPORTED_TYPES

__all__ = [
    "ingest_file",
    "get_page_count",
    "TextChunk",
    "count_tokens",
    "SUPPORTED_TYPES",
]
