"""
Token-aware text chunking with overlap.

This is the most critical module in the ingestion pipeline.  The quality
of chunks directly affects both summarisation (map-reduce) and RAG
(retrieval accuracy).

Strategy: Fixed-size token-based chunking with overlap
──────────────────────────────────────────────────────
We split text into chunks of ~512 tokens with ~50 tokens of overlap.

Why THIS strategy (and not alternatives)?
─────────────────────────────────────────
┌─────────────────────┬──────────────────────────────────────────────────┐
│ Strategy            │ Trade-offs                                       │
├─────────────────────┼──────────────────────────────────────────────────┤
│ Fixed-char-count    │ Simple but ignores token boundaries.  A 2000-   │
│                     │ char chunk might be 400 or 800 tokens depending  │
│                     │ on language — unpredictable context usage.       │
├─────────────────────┼──────────────────────────────────────────────────┤
│ Fixed-token-count   │ ✅ OUR CHOICE.  Guarantees each chunk fits in   │
│ (this module)       │ the model's context window.  Predictable cost   │
│                     │ per chunk.  Works for any language/format.       │
├─────────────────────┼──────────────────────────────────────────────────┤
│ Semantic chunking   │ Splits at topic/sentence boundaries.  Better    │
│ (e.g., by heading)  │ coherence but needs an extra embedding pass to  │
│                     │ detect boundaries, and chunk sizes vary wildly.  │
│                     │ Great for structured docs, poor for prose.       │
├─────────────────────┼──────────────────────────────────────────────────┤
│ Chapter-aware       │ Respects document structure.  But: chapters     │
│                     │ vary from 1 page to 50 pages, most PDFs don't   │
│                     │ expose heading structure reliably, and you still │
│                     │ need to sub-chunk long chapters.                 │
└─────────────────────┴──────────────────────────────────────────────────┘

Why overlap?
────────────
Without overlap, a sentence that spans the boundary between chunk N and
chunk N+1 gets split in half.  The embedding of each half is poor, and
retrieval misses it.  A 50-token overlap (~2-3 sentences) ensures
boundary content is represented in at least one chunk's embedding.

Why 512 tokens?
───────────────
• text-embedding-3-small supports 8191 tokens, but embeddings are
  highest quality for inputs of ~256-1024 tokens (empirically).
• 512 tokens ≈ 375 words ≈ roughly one substantial paragraph.
• A 500-page book (~125K words) produces ~330 chunks at 512 tokens.
  That's manageable for batch embedding and vector search.
• gpt-4o-mini has a 128K context window but we send at most ~5 chunks
  per RAG call (≈ 2560 tokens) — well within limits.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
import tiktoken

from app.ingestion.pdf_parser import PageText

logger = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────
DEFAULT_CHUNK_SIZE = 512         # tokens
DEFAULT_CHUNK_OVERLAP = 50       # tokens
ENCODING_NAME = "cl100k_base"   # tokeniser used by gpt-4o-mini & embedding-3-small


@dataclass
class TextChunk:
    """A single chunk of text with provenance metadata."""
    chunk_index: int             # 0-based position in the document
    content: str                 # the actual text
    page_start: int              # first page this chunk covers (1-indexed)
    page_end: int                # last page this chunk covers
    token_count: int             # exact token count (tiktoken)


def chunk_pages(
    pages: list[PageText],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split page-segmented text into fixed-token-size chunks with overlap.

    The algorithm:
    1. Concatenate all pages into a single token stream, but track which
       token indices correspond to which page numbers.
    2. Walk through the token stream in steps of (chunk_size - chunk_overlap),
       slicing out windows of chunk_size tokens.
    3. Decode each window back to text and record the page range.

    Parameters
    ----------
    pages : list[PageText]
        Output from pdf_parser or docx_parser.
    chunk_size : int
        Target tokens per chunk.
    chunk_overlap : int
        Number of tokens to overlap between consecutive chunks.

    Returns
    -------
    list[TextChunk]
        Chunks in document order, with page provenance.
    """
    if not pages:
        return []

    enc = tiktoken.get_encoding(ENCODING_NAME)

    # ── Step 1: tokenise and build page-boundary map ──────
    all_tokens: list[int] = []
    # Map: token_index → page_number  (for first & last token of each page)
    token_page_boundaries: list[tuple[int, int]] = []   # (start_token_idx, page_number)

    for page in pages:
        if not page.text.strip():
            continue
        start_idx = len(all_tokens)
        page_tokens = enc.encode(page.text, disallowed_special=())
        all_tokens.extend(page_tokens)
        token_page_boundaries.append((start_idx, page.page_number))

    total_tokens = len(all_tokens)

    if total_tokens == 0:
        logger.warning("chunk_pages_empty", reason="no tokens after encoding")
        return []

    # ── Step 2: sliding window over token stream ──────────
    step = max(1, chunk_size - chunk_overlap)
    chunks: list[TextChunk] = []

    for window_start in range(0, total_tokens, step):
        window_end = min(window_start + chunk_size, total_tokens)
        window_tokens = all_tokens[window_start:window_end]

        # Decode back to text
        content = enc.decode(window_tokens)

        # Determine page range for this window
        page_start = _token_to_page(window_start, token_page_boundaries)
        page_end = _token_to_page(window_end - 1, token_page_boundaries)

        chunks.append(
            TextChunk(
                chunk_index=len(chunks),
                content=content,
                page_start=page_start,
                page_end=page_end,
                token_count=len(window_tokens),
            )
        )

        # If we've reached the end, stop
        if window_end >= total_tokens:
            break

    logger.info(
        "chunking_complete",
        total_tokens=total_tokens,
        chunk_count=len(chunks),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        avg_chunk_tokens=total_tokens // max(len(chunks), 1),
    )

    return chunks


def _token_to_page(
    token_idx: int,
    boundaries: list[tuple[int, int]],
) -> int:
    """Find which page a token index belongs to.

    Uses binary-search-style logic: the page is the last boundary
    whose start_token_idx <= token_idx.
    """
    page = boundaries[0][1] if boundaries else 1

    for start_idx, page_number in boundaries:
        if start_idx <= token_idx:
            page = page_number
        else:
            break

    return page


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string.

    Useful for pre-flight checks (e.g., "is this chunk too big for
    the model's context window?").
    """
    enc = tiktoken.get_encoding(ENCODING_NAME)
    return len(enc.encode(text, disallowed_special=()))
