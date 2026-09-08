"""
FastAPI application entry point.

Wires together:
  • Structured logging (structlog)      → app/logging_config.py
  • Request-ID middleware               → app/middleware.py
  • CORS (permissive for dev)           → fastapi.middleware.cors
  • Database lifespan check             → app/db/engine.py
  • Health + debug endpoints            → below

The app is imported by uvicorn as `app.main:app`.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_engine
from app.logging_config import setup_logging
from app.middleware import RequestIDMiddleware
from app.auth.session_middleware import SessionMiddleware
from app.routes.auth import router as auth_router
from app.routes.documents import router as documents_router
from app.routes.queries import router as queries_router

# ── Configure logging BEFORE anything else ────────────────
setup_logging()
logger = structlog.get_logger()


# ── Lifespan (startup / shutdown) ─────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    logger.info("app_starting", log_level=settings.log_level)

    # Verify DB connectivity
    async with async_engine.begin() as conn:
        result = await conn.execute(text("SELECT 1"))
        logger.info("database_connected", result=result.scalar())

    yield

    logger.info("app_shutting_down")
    await async_engine.dispose()


# ── Create the app ────────────────────────────────────────
app = FastAPI(
    title="Book Summarizer & Query Agent",
    version="0.1.0",
    description="AI-powered book summarization and question-answering",
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost first) ──────────

# 1. CORS — allow the Next.js frontend (and any dev tools)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js dev server
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+):\d+",
    allow_credentials=True,           # needed for session cookies
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # so frontend JS can read it
)

# 2. Session — auto-creates anonymous sessions via cookies
app.add_middleware(SessionMiddleware)

# 3. Request-ID — generates UUID, binds to structlog, returns in header
app.add_middleware(RequestIDMiddleware)

# ── Routers ───────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(queries_router)


# ── Health endpoint ───────────────────────────────────────
@app.get("/health", tags=["infra"])
async def health_check():
    """Liveness probe — returns 200 if the app is up and DB is reachable."""
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return {"status": "degraded", "database": "unreachable", "error": str(e)}


# ── Debug: test LLM connectivity (remove before prod) ────
@app.get("/debug/llm-test", tags=["debug"])
async def debug_llm_test():
    """Quick smoke-test that the configured chat and embedding provider works.

    Returns token usage and latency for one embedding call and one
    chat completion call.  This endpoint exists only to prove Step 2
    is wired correctly — it will be removed or gated later.
    """
    from app.llm.azure_openai import chat_completion, embed_text

    # Test 1: Embed a short sentence
    embed_result = embed_text("The quick brown fox jumps over the lazy dog.")

    # Test 2: Chat completion
    chat_result = chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "In one sentence, what is a book summary?"},
        ],
        max_tokens=100,
    )

    return {
        "embedding_test": {
            "dimensions": len(embed_result.embedding),
            "first_5_values": embed_result.embedding[:5],
            "prompt_tokens": embed_result.prompt_tokens,
            "latency_ms": embed_result.latency_ms,
            "cost_usd": embed_result.estimated_cost_usd,
        },
        "chat_test": {
            "response": chat_result.content,
            "prompt_tokens": chat_result.prompt_tokens,
            "completion_tokens": chat_result.completion_tokens,
            "latency_ms": chat_result.latency_ms,
            "cost_usd": chat_result.estimated_cost_usd,
        },
    }
