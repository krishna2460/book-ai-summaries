"""
Query API routes — ask questions about a document.

Endpoints:
  POST  /documents/{id}/query   → ask a question, get answer + citations
  GET   /documents/{id}/queries → list all queries for a document
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_db
from app.db.models import Document, Query, LLMUsage
from app.graphs.query import build_rag_graph, build_initial_rag_state
from app.schemas import QueryRequest, QueryOut, ChunkCitation

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["queries"])


@router.post(
    "/{document_id}/query",
    response_model=QueryOut,
    status_code=status.HTTP_200_OK,
)
async def query_document(
    document_id: uuid.UUID,
    body: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Ask a question about a document.

    The question is embedded, similar chunks are retrieved from pgvector,
    and the answer is generated STRICTLY from the retrieved context.
    Citations reference specific chunks and page numbers.

    Unlike the upload endpoint, this runs synchronously — the user
    waits for the answer.  Typical latency: 2-5 seconds.

    Error codes:
      404 — document not found
      422 — question too short or document not yet processed
      500 — LLM or retrieval failure
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── Validate document exists and is processed ─────────
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if doc.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Document is not ready for queries. Current status: {doc.status}",
        )

    # ── Create query record (pending) ─────────────────────
    query_id = uuid.uuid4()
    query_record = Query(
        id=query_id,
        document_id=document_id,
        session_id=doc.session_id,
        user_id=doc.user_id,
        question=body.question,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(query_record)
    await db.flush()

    logger.info(
        "query_started",
        document_id=str(document_id),
        query_id=str(query_id),
        question_length=len(body.question),
    )

    try:
        # ── Build and run the RAG graph ───────────────────
        graph = build_rag_graph(session=db, document_id=document_id)
        initial_state = build_initial_rag_state(body.question)

        # ainvoke for async execution
        result_state = await graph.ainvoke(initial_state)

        # ── Check for graph errors ────────────────────────
        if result_state.get("error"):
            raise RuntimeError(result_state["error"])

        answer = result_state.get("answer", "")
        raw_citations = result_state.get("citations", [])

        if not answer:
            raise RuntimeError("RAG graph produced empty answer")

        # ── Build citation objects ────────────────────────
        cited_chunk_ids: list[uuid.UUID] = []
        citation_objects: list[ChunkCitation] = []

        for cite in raw_citations:
            chunk_id = uuid.UUID(cite["chunk_id"])
            cited_chunk_ids.append(chunk_id)
            citation_objects.append(
                ChunkCitation(
                    chunk_id=chunk_id,
                    chunk_index=cite["chunk_index"],
                    page_start=cite.get("page_start"),
                    page_end=cite.get("page_end"),
                    content_preview=cite.get("content_preview", ""),
                )
            )

        # ── Update query record ───────────────────────────
        query_record.answer = answer
        query_record.cited_chunk_ids = cited_chunk_ids
        query_record.status = "completed"

        # ── Store LLM usage records ──────────────────────
        llm_calls = result_state.get("llm_calls", [])
        for call_data in llm_calls:
            usage_row = LLMUsage(
                id=uuid.uuid4(),
                document_id=document_id,
                query_id=query_id,
                operation=call_data.get("operation", "rag_query"),
                model=call_data.get(
                    "model",
                    settings.gemini_chat_model if settings.gemini_api_key else settings.aiml_chat_model,
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
            db.add(usage_row)

        await db.flush()

        logger.info(
            "query_complete",
            query_id=str(query_id),
            answer_words=len(answer.split()),
            citations=len(citation_objects),
            llm_calls=len(llm_calls),
        )

        return QueryOut(
            id=query_id,
            document_id=document_id,
            question=body.question,
            answer=answer,
            citations=citation_objects,
            status="completed",
            created_at=query_record.created_at,
        )

    except Exception as e:
        logger.exception("query_failed", query_id=str(query_id), error=str(e))

        # The graph may have failed a SQL statement, so clear the aborted
        # transaction before recording the failed query.
        await db.rollback()
        failed_query = await db.get(Query, query_id)
        if failed_query:
            failed_query.status = "failed"
            failed_query.error_message = str(e)[:2000]
            await db.flush()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)[:200]}",
        )


@router.get(
    "/{document_id}/queries",
    response_model=list[QueryOut],
)
async def list_document_queries(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all queries made against a document.

    Returns queries in reverse chronological order (newest first).
    Used by the frontend to show chat history.

    Error codes:
      404 — document not found
    """
    # Verify document exists
    doc_result = await db.execute(
        select(Document.id).where(Document.id == document_id)
    )
    if doc_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    result = await db.execute(
        select(Query)
        .where(Query.document_id == document_id)
        .order_by(Query.created_at.desc())
    )
    queries = result.scalars().all()

    # Convert to response objects (without full citations for list view)
    return [
        QueryOut(
            id=q.id,
            document_id=q.document_id,
            question=q.question,
            answer=q.answer,
            citations=[],           # omitted in list view for performance
            status=q.status,
            error_message=q.error_message,
            created_at=q.created_at,
        )
        for q in queries
    ]
