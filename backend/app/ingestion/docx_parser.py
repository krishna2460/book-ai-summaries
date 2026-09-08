"""
DOCX text extraction using python-docx.

DOCX files don't have a native "page" concept — page breaks depend on
the rendering engine (Word, LibreOffice, etc.).  We handle this by:

1. Detecting explicit page-break characters (\\x0c form feeds and
   <w:br w:type="page"/> elements).
2. Using a heuristic fallback: estimate ~250 words per page when no
   explicit breaks are found.

This gives us "approximate page numbers" that are good enough for
citation purposes ("see around page 42") even if they don't match
the exact pagination a user would see in Word.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import structlog
from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError

logger = structlog.get_logger()

# Re-use the same dataclass as the PDF parser for a unified interface
from app.ingestion.pdf_parser import PageText


# Approximate words per page for the heuristic fallback
_WORDS_PER_PAGE = 250


def extract_docx_pages(file_bytes: bytes) -> list[PageText]:
    """Extract text from a DOCX file with approximate page boundaries.

    Parameters
    ----------
    file_bytes : bytes
        Raw .docx file content.

    Returns
    -------
    list[PageText]
        Text split into approximate pages.

    Raises
    ------
    ValueError
        If the file cannot be parsed as a DOCX.
    """
    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
    except (PackageNotFoundError, Exception) as e:
        logger.error("docx_parse_failed", error=str(e))
        raise ValueError(f"Could not parse DOCX: {e}") from e

    # ── Collect all paragraph texts ───────────────────────
    all_paragraphs: list[str] = []
    page_break_indices: list[int] = []      # paragraph indices where page breaks occur

    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        all_paragraphs.append(text)

        # Check for explicit page breaks in the paragraph's XML runs
        for run in para.runs:
            # python-docx exposes page breaks via the run's XML
            if run._element.xml and "w:br" in run._element.xml:
                if 'w:type="page"' in run._element.xml:
                    page_break_indices.append(i)
                    break

    if not all_paragraphs:
        raise ValueError("DOCX contains no text content.")

    # ── Split into pages ─────────────────────────────────
    if page_break_indices:
        # Use explicit page breaks
        pages = _split_by_breaks(all_paragraphs, page_break_indices)
    else:
        # Heuristic: split by approximate word count
        pages = _split_by_word_count(all_paragraphs)

    total_chars = sum(len(p.text) for p in pages)
    logger.info(
        "docx_extracted",
        page_count=len(pages),
        total_chars=total_chars,
        used_explicit_breaks=bool(page_break_indices),
    )

    if total_chars == 0:
        raise ValueError("DOCX contains no extractable text.")

    return pages


def _split_by_breaks(
    paragraphs: list[str], break_indices: list[int]
) -> list[PageText]:
    """Split paragraphs into pages using explicit page-break positions."""
    pages: list[PageText] = []
    prev = 0

    for idx in break_indices:
        page_text = "\n".join(paragraphs[prev : idx + 1])
        pages.append(PageText(page_number=len(pages) + 1, text=page_text))
        prev = idx + 1

    # Remaining paragraphs after last break
    if prev < len(paragraphs):
        page_text = "\n".join(paragraphs[prev:])
        pages.append(PageText(page_number=len(pages) + 1, text=page_text))

    return pages


def _split_by_word_count(paragraphs: list[str]) -> list[PageText]:
    """Split paragraphs into approximate pages by word count."""
    pages: list[PageText] = []
    current_lines: list[str] = []
    current_words = 0

    for para in paragraphs:
        word_count = len(para.split())
        current_lines.append(para)
        current_words += word_count

        if current_words >= _WORDS_PER_PAGE:
            page_text = "\n".join(current_lines)
            pages.append(PageText(page_number=len(pages) + 1, text=page_text))
            current_lines = []
            current_words = 0

    # Don't lose the last partial page
    if current_lines:
        page_text = "\n".join(current_lines)
        pages.append(PageText(page_number=len(pages) + 1, text=page_text))

    return pages


def get_docx_page_count(file_bytes: bytes) -> int:
    """Estimate page count without full extraction."""
    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
        total_words = sum(len(p.text.split()) for p in doc.paragraphs)
        return max(1, total_words // _WORDS_PER_PAGE)
    except Exception:
        return 0
