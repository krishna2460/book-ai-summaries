"""
Embedding & storage pipeline — write path.

Takes TextChunks from the ingestion pipeline (Step 3), embeds them via
OpenAI (Step 2), and stores them in the `chunks` table (Step 1).

This module is the bridge between ingestion and the database.  It:
  1. Calls embed_texts() in batches to get 1536-dim vectors
  2. Creates Chunk ORM objects with both text and embedding
  3. Bulk-inserts them in a single transaction
  4. Records LLM usage for cost tracking

Design decisions:
─────────────────
• Batch embedding (not one-at-a-time) — embed_texts() already batches
  at 100 texts per API call.  For a 500-page book (~330 chunks), that's
  ~4 API calls instead of 330.  Massive latency and cost savings.

• Bulk insert with flush — we don't commit inside this module.  The
  caller controls the transaction boundary.  This lets the caller
  update the document status and insert chunks atomically.

• Embedding dimension is 1536 (text-embedding-3-small).  If we ever
  switch models, only this module and the migration need to change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, LLMUsage
from app.ingestion.chunker import TextChunk
from app.llm.azure_openai import embed_texts, BatchEmbeddingResponse

logger = structlog.get_logger()


async def embed_and_store_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    chunks: list[TextChunk],
    *,
    batch_size: int = 100,
    request_id: str | None = None,
) -> tuple[list[Chunk], LLMUsage]:
    """Embed all chunks and store them in the database.

    Parameters
    ----------
    session : AsyncSession
        The database session (caller manages commit/rollback).
    document_id : uuid.UUID
        The document these chunks belong to.
    chunks : list[TextChunk]
        Output from the ingestion pipeline.
    batch_size : int
        Number of texts per OpenAI embedding API call.
    request_id : str | None
        Correlation ID for logging and llm_usage tracking.

    Returns
    -------
    tuple[list[Chunk], LLMUsage]
        The created Chunk ORM objects (with embeddings) and the
        LLMUsage record for this embedding operation.

    Raises
    ------
    Exception
        Any OpenAI or database error — caller should catch and
        mark the document as failed.
    """
    if not chunks:
        logger.warning("embed_and_store_no_chunks", document_id=str(document_id))
        # Return empty results with a zero-usage record
        usage = _create_usage_record(
            document_id=document_id,
            response=BatchEmbeddingResponse(),
            request_id=request_id,
        )
        session.add(usage)
        return [], usage

    logger.info(
        "embedding_started",
        document_id=str(document_id),
        chunk_count=len(chunks),
    )

    # ── Step 1: Extract texts for embedding ───────────────
    texts = [chunk.content for chunk in chunks]

    # ── Step 2: Call OpenAI embeddings ────────────────────
    # embed_texts() handles batching internally and returns all vectors
    # in input order, with aggregated usage metadata.
    embed_response: BatchEmbeddingResponse = embed_texts(
        texts, batch_size=batch_size
    )

    logger.info(
        "embedding_complete",
        document_id=str(document_id),
        total_tokens=embed_response.total_tokens,
        latency_ms=embed_response.latency_ms,
        cost_usd=embed_response.estimated_cost_usd,
    )

    # ── Step 3: Create Chunk ORM objects ──────────────────
    db_chunks: list[Chunk] = []

    for chunk, embedding_vector in zip(chunks, embed_response.embeddings):
        db_chunk = Chunk(
            id=uuid.uuid4(),
            document_id=document_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            token_count=chunk.token_count,
            embedding=embedding_vector,
            created_at=datetime.now(timezone.utc),
        )
        db_chunks.append(db_chunk)

    # ── Step 4: Bulk insert ───────────────────────────────
    session.add_all(db_chunks)
    await session.flush()          # assign IDs without committing

    logger.info(
        "chunks_stored",
        document_id=str(document_id),
        chunks_inserted=len(db_chunks),
    )

    # ── Step 5: Record LLM usage ─────────────────────────
    usage = _create_usage_record(
        document_id=document_id,
        response=embed_response,
        request_id=request_id,
    )
    session.add(usage)
    await session.flush()

    return db_chunks, usage


def _create_usage_record(
    document_id: uuid.UUID,
    response: BatchEmbeddingResponse,
    request_id: str | None,
) -> LLMUsage:
    """Create an LLMUsage row for the embedding operation."""
    return LLMUsage(
        id=uuid.uuid4(),
        document_id=document_id,
        query_id=None,
        operation="embed_chunks",
        model=response.model or "gemini-embedding-001",
        provider="gemini",
        prompt_tokens=response.prompt_tokens,
        completion_tokens=0,
        total_tokens=response.total_tokens,
        estimated_cost_usd=response.estimated_cost_usd,
        latency_ms=response.latency_ms,
        langfuse_trace_id=response.langfuse_trace_id,
        request_id=request_id,
        created_at=datetime.now(timezone.utc),
    )
