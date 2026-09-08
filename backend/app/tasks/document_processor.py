"""
Document processing background task.

This is the top-level orchestrator that runs when a file is uploaded.
It ties together ALL previous steps:

  Step 3: ingest_file()           → TextChunks
  Step 4: embed_and_store_chunks() → Chunk rows in DB
  Step 5: summarization graph      → 100-word summary

The entire pipeline runs as a background task (asyncio.create_task)
so the upload endpoint can return HTTP 202 immediately.

Error handling:
──────────────
• Every stage is wrapped in try/except.
• If ANY stage fails, the document status is set to "failed" with
  the error message stored in `document.error_message`.
• The document NEVER gets stuck in "processing" — it always transitions
  to either "completed" or "failed".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import AsyncSessionLocal
from app.db.models import Document, LLMUsage
from app.db.embedding_store import embed_and_store_chunks
from app.ingestion import ingest_file
from app.graphs.summarization import (
    build_summarization_graph,
    chunks_to_state,
)

logger = structlog.get_logger()


async def process_document(
    document_id: uuid.UUID,
    file_bytes: bytes,
    file_type: str,
    request_id: str | None = None,
) -> None:
    """Run the full ingestion → embedding → summarization pipeline.

    This function creates its own database session (not the request's
    session) because it runs as a background task after the HTTP
    response has been sent.

    Parameters
    ----------
    document_id : uuid.UUID
        The document to process (must already exist in DB).
    file_bytes : bytes
        Raw file content.
    file_type : str
        "pdf" or "docx".
    request_id : str | None
        Correlation ID for logging.
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id or "",
        document_id=str(document_id),
    )

    logger.info("document_processing_started")

    async with AsyncSessionLocal() as session:
        try:
            # ── Mark as processing ────────────────────────
            doc = await _get_document(session, document_id)
            if doc is None:
                logger.error("document_not_found")
                return

            doc.status = "processing"
            doc.updated_at = datetime.now(timezone.utc)
            await session.commit()

            # ── Stage 1: Ingest (parse + clean + chunk) ──
            logger.info("stage_ingest_started")
            text_chunks, page_count = ingest_file(file_bytes, file_type)
            doc.page_count = page_count
            logger.info(
                "stage_ingest_complete",
                page_count=page_count,
                chunk_count=len(text_chunks),
            )

            # ── Stage 2: Embed & store chunks ────────────
            logger.info("stage_embed_started")
            db_chunks, embed_usage = await embed_and_store_chunks(
                session=session,
                document_id=document_id,
                chunks=text_chunks,
                request_id=request_id,
            )
            doc.chunk_count = len(db_chunks)
            await session.commit()
            logger.info(
                "stage_embed_complete",
                chunks_stored=len(db_chunks),
                embed_tokens=embed_usage.total_tokens,
            )

            # ── Stage 3: Map-reduce summarization ────────
            logger.info("stage_summarize_started")
            graph = build_summarization_graph()
            initial_state = chunks_to_state(text_chunks)

            # Run the graph synchronously (LLM calls are sync)
            # LangGraph's invoke() handles the node execution
            result = graph.invoke(initial_state)

            # Check for errors in the graph execution
            if result.get("error"):
                raise RuntimeError(f"Summarization graph error: {result['error']}")

            final_summary = result.get("final_summary", "")
            if not final_summary:
                raise RuntimeError("Summarization produced empty summary")

            # ── Store LLM usage for summarization calls ──
            llm_calls = result.get("llm_calls", [])
            for call_data in llm_calls:
                usage_row = LLMUsage(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    operation=call_data.get("operation", "summarize"),
                    model=(
                        settings.gemini_chat_model
                        if settings.gemini_api_key
                        else settings.aiml_chat_model
                    ),
                    provider="gemini",
                    prompt_tokens=call_data.get("prompt_tokens", 0),
                    completion_tokens=call_data.get("completion_tokens", 0),
                    total_tokens=call_data.get("total_tokens", 0),
                    estimated_cost_usd=call_data.get("cost_usd", 0.0),
                    latency_ms=call_data.get("latency_ms", 0),
                    langfuse_trace_id=call_data.get("langfuse_trace_id"),
                    request_id=request_id,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(usage_row)

            # ── Mark as completed ─────────────────────────
            doc.summary = final_summary
            doc.status = "completed"
            doc.updated_at = datetime.now(timezone.utc)
            await session.commit()

            total_llm_cost = sum(c.get("cost_usd", 0) for c in llm_calls)
            total_llm_cost += embed_usage.estimated_cost_usd

            logger.info(
                "document_processing_complete",
                summary_words=len(final_summary.split()),
                total_llm_calls=len(llm_calls) + 1,  # +1 for embedding
                total_cost_usd=round(total_llm_cost, 6),
                graph_reduce_iterations=result.get("reduce_iterations", 0),
            )

        except Exception as e:
            logger.exception("document_processing_failed", error=str(e))
            # Mark as failed — NEVER fail silently
            try:
                doc = await _get_document(session, document_id)
                if doc:
                    doc.status = "failed"
                    error_text = str(e)
                    if "quota exceeded" in error_text.lower() or "resource_exhausted" in error_text.lower():
                        error_text = (
                            "Gemini API quota exceeded. Check Google AI Studio billing and rate limits, "
                            "then retry this document."
                        )
                    doc.error_message = error_text[:2000]
                    doc.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            except Exception as commit_err:
                logger.error(
                    "failed_to_mark_document_failed",
                    error=str(commit_err),
                )


async def _get_document(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> Document | None:
    """Fetch a document by ID."""
    result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    return result.scalar_one_or_none()
