"""
Text cleaning — normalise extracted text before chunking.

Raw text from PDFs and DOCX files is messy:
  • PDFs produce mid-word hyphens from line wrapping ("compre-\\nhensive")
  • Extra whitespace, stray form-feeds, NUL bytes
  • Headers/footers repeated on every page
  • Unicode oddities (smart quotes, em-dashes, ligatures)

This module applies a sequence of cleaning passes.  Each pass is a
small, testable function.  The pipeline is explicit — not a magic
regex — so it's easy to add or remove steps.
"""

from __future__ import annotations

import re
import unicodedata

import structlog

logger = structlog.get_logger()


def clean_text(text: str) -> str:
    """Apply the full cleaning pipeline to a piece of text.

    Parameters
    ----------
    text : str
        Raw extracted text (from a single page or a whole document).

    Returns
    -------
    str
        Cleaned text ready for chunking.
    """
    text = _remove_null_bytes(text)
    text = _normalize_unicode(text)
    text = _fix_hyphenated_line_breaks(text)
    text = _collapse_whitespace(text)
    text = _remove_form_feeds(text)
    text = text.strip()
    return text


def _remove_null_bytes(text: str) -> str:
    """Strip NUL characters that some PDF extractors leave in."""
    return text.replace("\x00", "")


def _normalize_unicode(text: str) -> str:
    """Normalize to NFC form and replace common typographic characters.

    NFC is the "composed" form — e.g. é as a single codepoint rather
    than e + combining accent.  This prevents duplicate-looking text
    from being treated as different during embedding.
    """
    text = unicodedata.normalize("NFC", text)

    # Replace smart quotes with ASCII equivalents
    replacements = {
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2013": "-",   # en-dash
        "\u2014": "--",  # em-dash
        "\u2026": "...", # ellipsis
        "\ufeff": "",    # BOM
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _fix_hyphenated_line_breaks(text: str) -> str:
    """Rejoin words split across lines by a hyphen.

    PDF extractors often produce "compre-\\nhensive" for "comprehensive".
    This regex matches a hyphen at end-of-line followed by a lowercase
    letter on the next line, and joins them.

    We only join when the next line starts with lowercase to avoid
    breaking intentional hyphens like "well-known\\nfact".
    """
    return re.sub(r"-\s*\n\s*([a-z])", r"\1", text)


def _collapse_whitespace(text: str) -> str:
    """Replace runs of spaces/tabs with a single space.

    Preserves single newlines (paragraph boundaries) but collapses
    runs of 3+ newlines to 2 (one blank line).
    """
    # Collapse horizontal whitespace
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _remove_form_feeds(text: str) -> str:
    """Remove form-feed characters (\\x0c) that mark page breaks."""
    return text.replace("\x0c", "\n")
