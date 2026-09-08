"""
PDF text extraction using pypdf.

Extracts text page-by-page, preserving page boundaries so that later
stages (chunking, citation) can reference specific pages.

Why pypdf over alternatives?
────────────────────────────
• pypdf is pure Python — no system deps like poppler (pdftotext) or
  Java (Apache Tika).  This keeps the Docker image small.
• It handles most "normal" PDFs (selectable text).  For scanned/OCR
  PDFs, you'd swap in `unstructured` or `pdfplumber` — the interface
  below (list of PageText) stays the same.
• It's fast: a 500-page PDF typically parses in <2 seconds.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import structlog
from pypdf import PdfReader

logger = structlog.get_logger()


@dataclass
class PageText:
    """One page of extracted text."""
    page_number: int          # 1-indexed (human-friendly)
    text: str


def extract_pdf_pages(file_bytes: bytes) -> list[PageText]:
    """Extract text from every page of a PDF.

    Parameters
    ----------
    file_bytes : bytes
        Raw PDF file content (as read from disk or an upload).

    Returns
    -------
    list[PageText]
        One entry per page, in order.  Pages with no extractable text
        are included with an empty string (so page numbering stays correct).

    Raises
    ------
    ValueError
        If the file cannot be parsed as a PDF.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        logger.error("pdf_parse_failed", error=str(e))
        raise ValueError(f"Could not parse PDF: {e}") from e

    pages: list[PageText] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(PageText(page_number=i + 1, text=text))

    total_chars = sum(len(p.text) for p in pages)
    logger.info(
        "pdf_extracted",
        page_count=len(pages),
        total_chars=total_chars,
        empty_pages=sum(1 for p in pages if not p.text.strip()),
    )

    if total_chars == 0:
        raise ValueError(
            "PDF contains no extractable text. It may be scanned/image-only."
        )

    return pages


def get_pdf_page_count(file_bytes: bytes) -> int:
    """Return the number of pages without full text extraction."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return len(reader.pages)
    except Exception:
        return 0
