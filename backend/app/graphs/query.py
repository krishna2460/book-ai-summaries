"""
RAG query graph — LangGraph implementation.

This graph answers questions about a specific document by retrieving
relevant chunks from pgvector and generating an answer grounded
STRICTLY in the retrieved context.

Architecture
────────────
    ┌───────────┐     ┌──────────────────┐     ┌─────────────────┐
    │ RETRIEVE  │────▶│ evaluate_context  │────▶│ GENERATE_ANSWER │
    │ embed +   │     │ (conditional edge)│     │ with citations  │
    │ search    │     └───────┬───────────┘     └─────────────────┘
    └───────────┘             │
                        ┌─────┴─────┐
                        │           │
                   insufficient   sufficient
                        │           │
                        ▼           └──▶ GENERATE_ANSWER
                   ┌──────────┐
                   │ BROADEN  │
                   │ re-search│──▶ GENERATE_ANSWER
                   │ with k×3 │
                   └──────────┘

HOW THIS DIFFERS FROM THE SUMMARIZATION GRAPH
──────────────────────────────────────────────
┌─────────────────────┬──────────────────────┬──────────────────────┐
│                     │ Summarization (S5)   │ RAG Query (S6)       │
├─────────────────────┼──────────────────────┼──────────────────────┤
│ When it runs        │ Once at upload time  │ Every user question  │
│ Processes           │ ALL chunks           │ Only top-k relevant  │
│ LLM task            │ Compress information │ Answer a question    │
│ Input size          │ Entire book          │ ~5 chunks (~2500 tok)│
│ Graph shape         │ MAP → REDUCE loop    │ RETRIEVE → ANSWER   │
│ Conditional edge    │ "still too long?"    │ "enough context?"    │
│ Output              │ 100-word summary     │ Answer + citations   │
│ DB interaction      │ Reads chunks (text)  │ Reads chunks (vector)│
└─────────────────────┴──────────────────────┴──────────────────────┘

Why they're SEPARATE graphs (not sub-graphs of one big graph):
  1. Different lifecycles — summarization runs once; RAG runs per question.
  2. Different state shapes — summarization tracks group_summaries and
     reduce_iterations; RAG tracks retrieved_chunks and citations.
  3. Different failure modes — a failed summary blocks the document;
     a failed query just returns an error for that question.
  4. Independent evolution — we can improve RAG (add reranking, HyDE)
     without touching the summarization pipeline.
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.vector_search import (
    SearchResult,
    search_similar_chunks,
    search_with_broadening,
)
from app.llm.azure_openai import ChatResponse, chat_completion
from app.ingestion.chunker import count_tokens

logger = structlog.get_logger()


# ── Configuration ─────────────────────────────────────────
INITIAL_TOP_K = 5
BROADENED_TOP_K = 15
MIN_GOOD_CHUNKS = 2
MIN_SIMILARITY = 0.55
ANSWER_MAX_TOKENS = 512
ANSWER_CONTEXT_MAX_CHARS = 9000


# ── Graph state ───────────────────────────────────────────
class RAGState(TypedDict):
    """State that flows between RAG graph nodes."""
    question: str
    retrieved_chunks: list[dict]        # serialised SearchResults
    context_sufficient: bool
    has_broadened: bool
    answer: str
    citations: list[dict]               # chunk_id, chunk_index, page range
    llm_calls: list[dict]               # usage metadata
    error: str


# ── Prompts ───────────────────────────────────────────────
ANSWER_SYSTEM_PROMPT = """You are a precise question-answering assistant. Answer the user's question using ONLY the provided context chunks from a book.

Rules:
1. First look for information in the context that directly answers the question, including descriptions of origins, development, causes, stages, or historical background.
2. If any relevant information is present, answer directly and confidently using that information. Do not refuse, hedge, or say you can provide information later.
3. Do NOT use external knowledge or invent details.
4. Only when the context is genuinely unrelated, reply exactly: "I cannot find enough information in the provided text to answer this question."
5. ALWAYS cite relevant sources using [Chunk X, Pages Y-Z] format after each claim.
6. Be concise and answer the question directly. Do not include meta-commentary about the instructions, the context, or what you could provide."""

ANSWER_USER_TEMPLATE = """Context chunks from the book:

{context}

Question: {question}

Answer (with citations):"""

INSUFFICIENT_CONTEXT_ANSWER = (
    "I cannot find enough information in the provided text to answer this question."
)


def _clean_answer(text: str) -> str:
    """Remove model padding and contradictory fallback text."""
    answer = " ".join(text.split())
    if INSUFFICIENT_CONTEXT_ANSWER in answer:
        return INSUFFICIENT_CONTEXT_ANSWER
    return answer


# ── Graph builder (closure captures session + document_id) ─

def build_rag_graph(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> Any:
    """Build a compiled RAG graph bound to a specific session and document.

    We use a closure-based factory because the retrieve and broaden
    nodes need database access.  Each query gets its own graph instance
    with its own session — clean and no global state.

    Parameters
    ----------
    session : AsyncSession
        The database session for this query.
    document_id : uuid.UUID
        The document to search within.

    Returns
    -------
    Compiled LangGraph that can be invoked with `await graph.ainvoke(state)`.
    """

    # ── Node: Retrieve chunks ─────────────────────────────
    async def retrieve_chunks(state: RAGState) -> dict[str, Any]:
        """Embed the question and retrieve top-k similar chunks.

        This node performs the actual vector similarity search against
        pgvector — it's not using the LLM's memory or conversation
        history.  The search is scoped to `document_id`.
        """
        question = state["question"]
        llm_calls = list(state.get("llm_calls", []))

        logger.info(
            "rag_retrieve_started",
            document_id=str(document_id),
            question_length=len(question),
            top_k=INITIAL_TOP_K,
        )

        try:
            results, embed_response = await search_similar_chunks(
                session=session,
                document_id=document_id,
                query_text=question,
                top_k=INITIAL_TOP_K,
            )

            llm_calls.append({
                "operation": "rag_embed_query",
                "prompt_tokens": embed_response.prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": embed_response.total_tokens,
                "cost_usd": embed_response.estimated_cost_usd,
                "latency_ms": embed_response.latency_ms,
                "langfuse_trace_id": embed_response.langfuse_trace_id,
            })

            serialised = _serialise_results(results)

            logger.info(
                "rag_retrieve_complete",
                results_found=len(results),
                best_similarity=results[0].similarity if results else None,
            )

            return {
                "retrieved_chunks": serialised,
                "llm_calls": llm_calls,
                "error": "",
            }

        except Exception as e:
            logger.error("rag_retrieve_failed", error=str(e))
            return {
                "retrieved_chunks": [],
                "llm_calls": llm_calls,
                "error": f"Retrieval failed: {e}",
            }

    # ── Node: Broaden retrieval ───────────────────────────
    async def broaden_retrieval(state: RAGState) -> dict[str, Any]:
        """Re-retrieve with a larger k when initial context is insufficient.

        Reuses the already-computed embedding via search_with_broadening
        to avoid a redundant API call.
        """
        question = state["question"]
        llm_calls = list(state.get("llm_calls", []))

        logger.info(
            "rag_broadening",
            document_id=str(document_id),
            broadened_k=BROADENED_TOP_K,
        )

        try:
            results, embed_response = await search_with_broadening(
                session=session,
                document_id=document_id,
                query_text=question,
                initial_k=BROADENED_TOP_K,
                max_k=BROADENED_TOP_K,
                min_results=MIN_GOOD_CHUNKS,
                min_similarity=MIN_SIMILARITY,
            )

            llm_calls.append({
                "operation": "rag_embed_broadened",
                "prompt_tokens": embed_response.prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": embed_response.total_tokens,
                "cost_usd": embed_response.estimated_cost_usd,
                "latency_ms": embed_response.latency_ms,
                "langfuse_trace_id": embed_response.langfuse_trace_id,
            })

            serialised = _serialise_results(results)

            logger.info(
                "rag_broadened_complete",
                results_found=len(results),
            )

            return {
                "retrieved_chunks": serialised,
                "has_broadened": True,
                "llm_calls": llm_calls,
                "error": "",
            }

        except Exception as e:
            logger.error("rag_broaden_failed", error=str(e))
            return {
                "has_broadened": True,
                "llm_calls": llm_calls,
                "error": f"Broadened retrieval failed: {e}",
            }

    # ── Node: Generate answer with citations ──────────────
    async def generate_answer(state: RAGState) -> dict[str, Any]:
        """Answer the question using ONLY the retrieved context.

        The prompt explicitly instructs the LLM to:
          • Not use external knowledge
          • Cite chunks with [Chunk X, Pages Y-Z] format
          • Admit when context is insufficient
        """
        question = state["question"]
        chunks = state["retrieved_chunks"]
        llm_calls = list(state.get("llm_calls", []))

        if not chunks:
            return {
                "answer": "No relevant content was found in the document for this question.",
                "citations": [],
                "llm_calls": llm_calls,
                "error": "",
            }

        # Keep broadened retrieval within the chat model context window.
        context_parts = []
        context_size = 0
        context_chunks = []
        for chunk in chunks:
            part = (
                f"[Chunk {chunk['chunk_index']}, "
                f"Pages {chunk['page_start']}-{chunk['page_end']}]:\n"
                f"{chunk['content']}"
            )
            remaining = ANSWER_CONTEXT_MAX_CHARS - context_size
            if remaining <= 0:
                break
            context_parts.append(part[:remaining])
            context_chunks.append(chunk)
            context_size += len(part)
        context = "\n\n---\n\n".join(context_parts)

        logger.info(
            "rag_generate_started",
            context_chunks=len(chunks),
            context_tokens=count_tokens(context),
        )

        try:
            response: ChatResponse = chat_completion(
                messages=[
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": ANSWER_USER_TEMPLATE.format(
                        context=context,
                        question=question,
                    )},
                ],
                temperature=0.2,
                max_tokens=ANSWER_MAX_TOKENS,
            )

            llm_calls.append({
                "operation": "rag_generate_answer",
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
                "cost_usd": response.estimated_cost_usd,
                "latency_ms": response.latency_ms,
                "langfuse_trace_id": response.langfuse_trace_id,
            })

            # Build citation list from the chunks we used
            citations = [
                {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_index": chunk["chunk_index"],
                    "page_start": chunk["page_start"],
                    "page_end": chunk["page_end"],
                    "content_preview": chunk["content"][:150] + "...",
                }
                for chunk in context_chunks
            ]

            logger.info(
                "rag_generate_complete",
                answer_words=len(response.content.split()),
                citations_count=len(citations),
                tokens=response.total_tokens,
            )

            answer = _clean_answer(response.content)
            return {
                "answer": answer,
                "citations": citations,
                "llm_calls": llm_calls,
                "error": "",
            }

        except Exception as e:
            logger.error("rag_generate_failed", error=str(e))
            return {
                "answer": "",
                "citations": [],
                "llm_calls": llm_calls,
                "error": f"Answer generation failed: {e}",
            }

    # ── Conditional edge: evaluate context quality ────────
    def evaluate_context(state: RAGState) -> str:
        """Decide whether retrieved context is sufficient.

        Routes to:
          • "generate" — enough good chunks, proceed to answer
          • "broaden"  — too few or too low similarity, re-retrieve
          • "generate_anyway" — already broadened, just answer with what we have
          • "error" — something went wrong

        This is the conditional edge that makes the RAG graph non-linear.
        """
        if state.get("error"):
            logger.warning("rag_routing_error", error=state["error"])
            return "error"

        chunks = state.get("retrieved_chunks", [])
        has_broadened = state.get("has_broadened", False)

        # Count chunks above similarity threshold
        good_chunks = [
            c for c in chunks
            if c.get("similarity", 0) >= MIN_SIMILARITY
        ]

        logger.info(
            "rag_evaluating_context",
            total_chunks=len(chunks),
            good_chunks=len(good_chunks),
            threshold=MIN_SIMILARITY,
            has_broadened=has_broadened,
        )

        if len(good_chunks) >= MIN_GOOD_CHUNKS:
            return "generate"

        if not has_broadened:
            logger.info("rag_routing_to_broaden", reason="insufficient good chunks")
            return "broaden"

        # Already broadened — generate with what we have
        logger.info("rag_routing_to_generate_anyway", reason="already broadened")
        return "generate_anyway"

    # ── Build the graph ───────────────────────────────────
    graph = StateGraph(RAGState)

    # Nodes
    graph.add_node("retrieve_chunks", retrieve_chunks)
    graph.add_node("broaden_retrieval", broaden_retrieval)
    graph.add_node("generate_answer", generate_answer)

    # Edges
    graph.set_entry_point("retrieve_chunks")

    # Conditional edge after retrieval
    graph.add_conditional_edges(
        "retrieve_chunks",
        evaluate_context,
        {
            "generate": "generate_answer",
            "broaden": "broaden_retrieval",
            "generate_anyway": "generate_answer",
            "error": END,
        },
    )

    # After broadening, always generate
    graph.add_edge("broaden_retrieval", "generate_answer")

    # Answer is the final node
    graph.add_edge("generate_answer", END)

    return graph.compile()


# ── Helper ────────────────────────────────────────────────

def _serialise_results(results: list[SearchResult]) -> list[dict]:
    """Convert SearchResult dataclasses to JSON-serialisable dicts."""
    return [
        {
            "chunk_id": str(r.chunk_id),
            "chunk_index": r.chunk_index,
            "content": r.content,
            "page_start": r.page_start,
            "page_end": r.page_end,
            "token_count": r.token_count,
            "distance": r.distance,
            "similarity": r.similarity,
        }
        for r in results
    ]


def build_initial_rag_state(question: str) -> RAGState:
    """Create the initial state for a RAG query."""
    return RAGState(
        question=question,
        retrieved_chunks=[],
        context_sufficient=False,
        has_broadened=False,
        answer="",
        citations=[],
        llm_calls=[],
        error="",
    )
