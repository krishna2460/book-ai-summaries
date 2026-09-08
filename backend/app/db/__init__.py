"""
Database sub-package — public API.

Exports:
  • Engine/session: get_db, async_engine
  • Models: all ORM models
  • Write path: embed_and_store_chunks
  • Read path: search_similar_chunks, search_with_broadening
"""

from app.db.engine import get_db, async_engine, AsyncSessionLocal
from app.db.models import Base, User, Session, Document, Chunk, Query, LLMUsage
from app.db.embedding_store import embed_and_store_chunks
from app.db.vector_search import (
    search_similar_chunks,
    search_with_broadening,
    SearchResult,
)

__all__ = [
    # engine
    "get_db",
    "async_engine",
    "AsyncSessionLocal",
    # models
    "Base",
    "User",
    "Session",
    "Document",
    "Chunk",
    "Query",
    "LLMUsage",
    # write path
    "embed_and_store_chunks",
    # read path
    "search_similar_chunks",
    "search_with_broadening",
    "SearchResult",
]
