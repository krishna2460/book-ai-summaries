"""
OpenAI-compatible LLM wrapper — centralised access with retry & error handling.

This module is the ONLY place in the codebase that talks to an LLM provider.
Every other module (graphs, routes, ingestion) imports from here.

Design decisions:
─────────────────
1. **Thin wrapper, not an abstraction layer.**  We use the `openai` SDK
    directly, not a framework-specific chat client, for
   the wrapper.  LangGraph nodes will call these functions — this keeps
   the LLM plumbing testable independently of the graph logic.

2. **Automatic retry with exponential backoff.**  OpenAI returns
   429 (rate limit) and 5xx errors transiently.  We retry up to 3 times
   with jitter so the caller doesn't need to handle retries.

3. **Structured return types.**  Both functions return a dataclass with
   the result *and* usage metadata (tokens, latency), which feeds
   directly into the `llm_usage` table later.

4. **No global state.**  The client is created via `get_client()` (cached)
   using settings from `app.config`.  Tests can patch `get_client`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from threading import Lock
from typing import Optional

import structlog
from openai import OpenAI

from app.config import settings
from app.observability import get_langfuse

logger = structlog.get_logger()

# ── Retry config ──────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0          # seconds — doubled each retry
_client_rotation_lock = Lock()
_client_rotation_index = 0

# ── Cost per 1 K tokens (USD) — gpt-4o-mini & embedding-3-small ──
_COST_TABLE: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"prompt": 0.0, "completion": 0.0},
    "text-embedding-3-small": {"prompt": 0.0, "completion": 0.0},
}


# ── Response dataclasses ─────────────────────────────────
@dataclass
class ChatResponse:
    """Result of a chat completion call."""
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""
    langfuse_trace_id: Optional[str] = None


@dataclass
class EmbeddingResponse:
    """Result of an embedding call."""
    embedding: list[float] = field(default_factory=list)
    prompt_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""
    langfuse_trace_id: Optional[str] = None


@dataclass
class BatchEmbeddingResponse:
    """Result of a batch embedding call (multiple texts)."""
    embeddings: list[list[float]] = field(default_factory=list)
    prompt_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""
    langfuse_trace_id: Optional[str] = None


# ── Client factory ────────────────────────────────────────
@lru_cache
def _get_groq_client():
    """Create and cache the Groq chat client when configured."""
    if not settings.groq_api_key:
        return None
    return OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)


@lru_cache
def _get_embedding_client_pool():
    """Create clients for the configured embedding provider keys."""
    if settings.gemini_api_keys:
        keys = [key.strip() for key in settings.gemini_api_keys.split(",") if key.strip()]
    elif settings.gemini_api_key:
        keys = [settings.gemini_api_key]
    else:
        keys = [settings.aiml_api_key]

    if settings.gemini_api_key or settings.gemini_api_keys:
        return tuple(OpenAI(api_key=key, base_url=settings.gemini_base_url) for key in keys)
    return (OpenAI(api_key=settings.aiml_api_key, base_url=settings.aiml_base_url),)


def get_chat_client():
    """Return Groq for chat, falling back to the configured compatible API."""
    groq_client = _get_groq_client()
    if groq_client:
        return groq_client
    return get_embedding_client()


def get_embedding_client():
    """Return the next configured embedding client.

    Gemini keys rotate round-robin between embedding requests.
    """
    global _client_rotation_index
    clients = _get_embedding_client_pool()
    with _client_rotation_lock:
        client = clients[_client_rotation_index % len(clients)]
        _client_rotation_index += 1
    return client


def get_client():
    """Backward-compatible alias for the chat client."""
    return get_chat_client()


def _chat_model(deployment: Optional[str]) -> str:
    return deployment or (
        settings.groq_chat_model
        if settings.groq_api_key
        else settings.gemini_chat_model if settings.gemini_api_key else settings.aiml_chat_model
    )


def _embedding_model(deployment: Optional[str]) -> str:
    return deployment or (
        settings.gemini_embedding_model
        if settings.gemini_api_key
        else settings.aiml_embedding_model
    )


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts."""
    costs = _COST_TABLE.get(model, {"prompt": 0.0, "completion": 0.0})
    return (
        (prompt_tokens / 1000) * costs["prompt"]
        + (completion_tokens / 1000) * costs["completion"]
    )


def _should_retry(error: Exception) -> bool:
    """Decide if an error is transient and worth retrying."""
    status_code = getattr(error, "status_code", None)
    error_text = str(error).lower()
    if (
        status_code == 429
        and (
            "quota exceeded" in error_text
            or "resource_exhausted" in error_text
            or "free_tier" in error_text
            or "per day" in error_text
        )
    ):
        return False
    if status_code == 429 or (status_code and status_code >= 500):
        return True
    return False


# ── Chat completion ───────────────────────────────────────
def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    deployment: Optional[str] = None,
) -> ChatResponse:
    """Send a chat completion request to OpenAI.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...} dicts
    temperature : float — lower = more deterministic
    max_tokens : int — cap on response length
    deployment : str | None — override the default deployment name

    Returns
    -------
    ChatResponse with content, token usage, cost, and latency.

    Raises
    ------
    APIError — after all retries are exhausted.
    """
    client = get_chat_client()
    model = _chat_model(deployment)
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = time.perf_counter()
            langfuse = get_langfuse()
            trace = None
            if langfuse:
                trace = langfuse.trace(name="chat_completion", model=model)
                
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            usage = response.usage
            prompt_tok = getattr(usage, "prompt_tokens", 0) or 0
            comp_tok = getattr(usage, "completion_tokens", 0) or 0
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise RuntimeError(
                    f"LLM returned an empty response for model {model}"
                )

            if trace:
                trace.update(
                    input=messages,
                    output=content,
                    usage={"promptTokens": prompt_tok, "completionTokens": comp_tok, "totalTokens": prompt_tok + comp_tok}
                )

            result = ChatResponse(
                content=content,
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                total_tokens=prompt_tok + comp_tok,
                estimated_cost_usd=_estimate_cost(model, prompt_tok, comp_tok),
                latency_ms=latency_ms,
                model=model,
                langfuse_trace_id=trace.id if trace else None,
            )

            logger.info(
                "chat_completion_success",
                model=model,
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                latency_ms=latency_ms,
                attempt=attempt,
            )
            return result

        except Exception as e:
            last_error = e
            if _should_retry(e) and attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "chat_completion_retry",
                    error=str(e),
                    attempt=attempt,
                    next_delay_s=delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "chat_completion_failed",
                    error=str(e),
                    attempt=attempt,
                )
                raise


# ── Embeddings (single text) ─────────────────────────────
def embed_text(
    text: str,
    *,
    deployment: Optional[str] = None,
) -> EmbeddingResponse:
    """Embed a single piece of text.

    Returns
    -------
    EmbeddingResponse with the 1536-dim vector, usage, and latency.
    """
    client = get_embedding_client()
    model = _embedding_model(deployment)
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = time.perf_counter()
            langfuse = get_langfuse()
            trace = None
            if langfuse:
                trace = langfuse.trace(name="embed_text", model=model)

            response = client.embeddings.create(
                model=model,
                input=text,
                dimensions=1536 if settings.gemini_api_key else None,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
            
            if trace:
                trace.update(input=text, usage={"promptTokens": prompt_tok, "totalTokens": prompt_tok})

            result = EmbeddingResponse(
                embedding=list(response.data[0].embedding),
                prompt_tokens=prompt_tok,
                total_tokens=prompt_tok,
                estimated_cost_usd=_estimate_cost(model, prompt_tok, 0),
                latency_ms=latency_ms,
                model=model,
                langfuse_trace_id=trace.id if trace else None,
            )

            logger.info(
                "embed_text_success",
                model=model,
                prompt_tokens=prompt_tok,
                latency_ms=latency_ms,
                dimensions=len(result.embedding),
            )
            return result

        except Exception as e:
            last_error = e
            if _should_retry(e) and attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "embed_text_retry",
                    error=str(e),
                    attempt=attempt,
                    next_delay_s=delay,
                )
                time.sleep(delay)
            else:
                logger.error("embed_text_failed", error=str(e), attempt=attempt)
                raise


# ── Embeddings (batch) ────────────────────────────────────
def embed_texts(
    texts: list[str],
    *,
    deployment: Optional[str] = None,
    batch_size: int = 100,
) -> BatchEmbeddingResponse:
    """Embed multiple texts, automatically batching to stay within limits.

    The OpenAI embeddings endpoint accepts up to ~2048 items, but
    we batch at `batch_size` (default 100) to keep request payloads
    manageable and avoid timeouts on large books.

    Returns
    -------
    BatchEmbeddingResponse with all embeddings in input order.
    """
    client = get_embedding_client()
    model = _embedding_model(deployment)

    langfuse = get_langfuse()
    trace = None
    if langfuse:
        trace = langfuse.trace(name="embed_texts", model=model)

    all_embeddings: list[list[float]] = []
    total_prompt_tokens = 0
    total_latency_ms = 0

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                start = time.perf_counter()
                response = client.embeddings.create(
                    model=model,
                    input=batch,
                    dimensions=1536 if settings.gemini_api_key else None,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)

                prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                total_prompt_tokens += prompt_tok
                total_latency_ms += latency_ms
                
                if trace:
                    trace.generation(
                        name="embed_batch",
                        input=batch,
                        model=model,
                        usage={"promptTokens": prompt_tok, "totalTokens": prompt_tok}
                    )

                all_embeddings.extend([list(item.embedding) for item in response.data])

                logger.info(
                    "embed_batch_success",
                    model=model,
                    batch_start=i,
                    batch_size=len(batch),
                    prompt_tokens=prompt_tok,
                    latency_ms=latency_ms,
                )
                break  # success — exit retry loop

            except Exception as e:
                last_error = e
                if _should_retry(e) and attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "embed_batch_retry",
                        error=str(e),
                        batch_start=i,
                        attempt=attempt,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "embed_batch_failed",
                        error=str(e),
                        batch_start=i,
                        attempt=attempt,
                    )
                    raise

    return BatchEmbeddingResponse(
        embeddings=all_embeddings,
        prompt_tokens=total_prompt_tokens,
        total_tokens=total_prompt_tokens,
        estimated_cost_usd=_estimate_cost(model, total_prompt_tokens, 0),
        latency_ms=total_latency_ms,
        model=model,
        langfuse_trace_id=trace.id if trace else None,
    )
