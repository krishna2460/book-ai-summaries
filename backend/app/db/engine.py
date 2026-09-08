"""
Async SQLAlchemy engine & session factory.

Two engines exist:
  • async_engine  – used by the running FastAPI app (asyncpg driver)
  • sync_engine   – used only by Alembic migrations (psycopg2 driver)

The `get_db` async generator is a FastAPI dependency that yields a
per-request session and commits/rollbacks automatically.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import create_engine

from app.config import settings

# ── Async engine (app runtime) ────────────────────────────
async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,         # reconnect on stale connections
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,     # prevent lazy-load surprises after commit
)

# ── Sync engine (Alembic only) ────────────────────────────
sync_engine = create_engine(
    settings.database_url_sync,
    echo=False,
    pool_pre_ping=True,
)


async def get_db() -> AsyncSession:                     # type: ignore[misc]
    """FastAPI dependency — yields one session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
