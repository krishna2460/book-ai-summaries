"""
Ingestion pipeline — the top-level function that other modules call.

This is the single entry-point for converting a raw file (bytes) into
a list of cleaned, chunked TextChunks with page provenance.

Flow:
  file bytes → detect format → parse → clean each page → chunk → return

Every step is delegated to a focused module:
  • pdf_parser / docx_parser → extract PageTexts
  • text_cleaner             → normalise text
  • chunker                  → split into token-sized chunks
"""

from __future__ import annotations

import structlog

from app.ingestion.chunker import TextChunk, chunk_pages, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP
from app.ingestion.docx_parser import extract_docx_pages, get_docx_page_count
from app.ingestion.pdf_parser import PageText, extract_pdf_pages, get_pdf_page_count
from app.ingestion.text_cleaner import clean_text

logger = structlog.get_logger()

# Supported file extensions
SUPPORTED_TYPES = {"pdf", "docx"}


def ingest_file(
    file_bytes: bytes,
    file_type: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[list[TextChunk], int]:
    """Parse, clean, and chunk a file in one call.

    Parameters
    ----------
    file_bytes : bytes
        Raw file content.
    file_type : str
        "pdf" or "docx" (lowercase).
    chunk_size : int
        Target tokens per chunk.
    chunk_overlap : int
        Overlap tokens between consecutive chunks.

    Returns
    -------
    tuple[list[TextChunk], int]
        (chunks, page_count)

    Raises
    ------
    ValueError
        If file_type is unsupported or the file can't be parsed.
    """
    file_type = file_type.lower().strip(".")

    if file_type not in SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported file type: '{file_type}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_TYPES))}"
        )

    logger.info(
        "ingestion_started",
        file_type=file_type,
        file_size_bytes=len(file_bytes),
    )

    # ── Step 1: Parse ─────────────────────────────────────
    if file_type == "pdf":
        pages = extract_pdf_pages(file_bytes)
        page_count = len(pages)
    else:  # docx
        pages = extract_docx_pages(file_bytes)
        page_count = len(pages)

    # ── Step 2: Clean each page ───────────────────────────
    cleaned_pages: list[PageText] = []
    for page in pages:
        cleaned = clean_text(page.text)
        if cleaned:  # skip completely empty pages
            cleaned_pages.append(
                PageText(page_number=page.page_number, text=cleaned)
            )

    logger.info(
        "text_cleaned",
        original_pages=len(pages),
        non_empty_pages=len(cleaned_pages),
    )

    # ── Step 3: Chunk ─────────────────────────────────────
    chunks = chunk_pages(
        cleaned_pages,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    logger.info(
        "ingestion_complete",
        page_count=page_count,
        chunk_count=len(chunks),
    )

    return chunks, page_count


def get_page_count(file_bytes: bytes, file_type: str) -> int:
    """Quick page-count estimate without full ingestion."""
    file_type = file_type.lower().strip(".")
    if file_type == "pdf":
        return get_pdf_page_count(file_bytes)
    elif file_type == "docx":
        return get_docx_page_count(file_bytes)
    return 0
