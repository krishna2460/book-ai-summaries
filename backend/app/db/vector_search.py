"""
Vector similarity search — read path.

Queries the `chunks` table using pgvector's cosine distance operator
to find the most semantically similar chunks to a given question.

How pgvector similarity search works
─────────────────────────────────────
pgvector adds custom operators to PostgreSQL:

  <=>  cosine distance      (0 = identical, 2 = opposite)
  <->  L2 (Euclidean) distance
  <#>  inner product (negative, for max-inner-product search)

We use cosine distance (<=>).  The query is:

  SELECT *, embedding <=> :query_vec AS distance
  FROM chunks
  WHERE document_id = :doc_id
  ORDER BY distance ASC
  LIMIT :k

The HNSW index created in migration 0001 makes this an approximate
nearest-neighbor (ANN) search:
  • Build time: O(n log n)
  • Query time: O(log n) with >95% recall
  • Works well up to millions of vectors

For a 500-page book (~330 chunks), even a brute-force scan would be
fast.  The HNSW index future-proofs us if we ever have many documents'
chunks in a single table without the document_id filter.

Why cosine distance (not L2 or inner product)?
──────────────────────────────────────────────
text-embedding-3-small embeddings are normalised (unit vectors), so
cosine distance and L2 distance give the same ranking.  But cosine
is the conventional choice for text retrieval and the one OpenAI
recommends.  The HNSW index was built with vector_cosine_ops to match.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.azure_openai import embed_text, EmbeddingResponse

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """A single chunk returned by similarity search."""
    chunk_id: uuid.UUID
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    token_count: int | None
    distance: float                # cosine distance (lower = more similar)
    similarity: float              # 1 - distance (higher = more similar)


async def search_similar_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    query_text: str,
    *,
    top_k: int = 5,
) -> tuple[list[SearchResult], EmbeddingResponse]:
    """Find the top-k most similar chunks to a query string.

    Steps:
    1. Embed the query text using the same model (text-embedding-3-small).
    2. Run a cosine-distance query against the chunks table, filtered by
       document_id.
    3. Return results sorted by similarity (highest first).

    Parameters
    ----------
    session : AsyncSession
        Database session.
    document_id : uuid.UUID
        Restrict search to this document's chunks.
    query_text : str
        The user's question or search query.
    top_k : int
        Number of results to return (default 5).

    Returns
    -------
    tuple[list[SearchResult], EmbeddingResponse]
        The matching chunks (with similarity scores) and the embedding
        usage metadata (for llm_usage tracking).
    """
    logger.info(
        "vector_search_started",
        document_id=str(document_id),
        query_length=len(query_text),
        top_k=top_k,
    )

    # ── Step 1: Embed the query ───────────────────────────
    embed_response = embed_text(query_text)
    query_embedding = embed_response.embedding

    # ── Step 2: Cosine similarity search via pgvector ─────
    # We use raw SQL because pgvector operators (<=>)  aren't
    # natively supported by SQLAlchemy's query builder.
    #
    # The ::vector cast ensures PostgreSQL treats our array as
    # a pgvector type for the <=> operator.

    sql = text("""
        SELECT
            id,
            chunk_index,
            content,
            page_start,
            page_end,
            token_count,
            embedding <=> CAST(:query_vec AS vector) AS distance
        FROM chunks
        WHERE document_id = :doc_id
          AND embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT :k
    """)

    # pgvector expects the vector as a string like '[0.1, 0.2, ...]'
    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    result = await session.execute(
        sql,
        {
            "query_vec": vec_str,
            "doc_id": str(document_id),
            "k": top_k,
        },
    )

    rows = result.fetchall()

    # ── Step 3: Build SearchResult objects ────────────────
    results: list[SearchResult] = []
    for row in rows:
        distance = float(row.distance)
        results.append(
            SearchResult(
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                content=row.content,
                page_start=row.page_start,
                page_end=row.page_end,
                token_count=row.token_count,
                distance=distance,
                similarity=1.0 - distance,     # cosine similarity
            )
        )

    logger.info(
        "vector_search_complete",
        document_id=str(document_id),
        results_found=len(results),
        best_similarity=results[0].similarity if results else None,
        embed_tokens=embed_response.prompt_tokens,
        embed_latency_ms=embed_response.latency_ms,
    )

    return results, embed_response


async def search_with_broadening(
    session: AsyncSession,
    document_id: uuid.UUID,
    query_text: str,
    *,
    initial_k: int = 5,
    max_k: int = 15,
    min_results: int = 3,
    min_similarity: float = 0.3,
) -> tuple[list[SearchResult], EmbeddingResponse]:
    """Search with automatic broadening if initial results are poor.

    If the initial search returns fewer than `min_results` above
    `min_similarity`, we broaden by increasing k.  This will be used
    by the RAG query graph's conditional edge in Step 6.

    Parameters
    ----------
    session : AsyncSession
        Database session.
    document_id : uuid.UUID
        Target document.
    query_text : str
        The user's question.
    initial_k : int
        First attempt retrieval count.
    max_k : int
        Maximum retrieval count for broadened search.
    min_results : int
        Minimum number of "good" results needed.
    min_similarity : float
        Threshold for what counts as a "good" result.

    Returns
    -------
    tuple[list[SearchResult], EmbeddingResponse]
        Results and embedding metadata.
    """
    results, embed_response = await search_similar_chunks(
        session, document_id, query_text, top_k=initial_k
    )

    # Count how many results are above the similarity threshold
    good_results = [r for r in results if r.similarity >= min_similarity]

    if len(good_results) >= min_results:
        logger.info("search_quality_sufficient", good_count=len(good_results))
        return results, embed_response

    # Broaden: re-query with larger k
    # We re-use the already-computed embedding to avoid a redundant API call
    logger.info(
        "search_broadening",
        initial_good=len(good_results),
        broadened_k=max_k,
    )

    sql = text("""
        SELECT
            id,
            chunk_index,
            content,
            page_start,
            page_end,
            token_count,
            embedding <=> CAST(:query_vec AS vector) AS distance
        FROM chunks
        WHERE document_id = :doc_id
          AND embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT :k
    """)

    vec_str = "[" + ",".join(str(v) for v in embed_response.embedding) + "]"

    result = await session.execute(
        sql,
        {
            "query_vec": vec_str,
            "doc_id": str(document_id),
            "k": max_k,
        },
    )

    rows = result.fetchall()
    broadened_results: list[SearchResult] = []
    for row in rows:
        distance = float(row.distance)
        broadened_results.append(
            SearchResult(
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                content=row.content,
                page_start=row.page_start,
                page_end=row.page_end,
                token_count=row.token_count,
                distance=distance,
                similarity=1.0 - distance,
            )
        )

    logger.info(
        "search_broadened_complete",
        broadened_results=len(broadened_results),
    )

    return broadened_results, embed_response
