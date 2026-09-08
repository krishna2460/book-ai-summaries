"""
SQLAlchemy ORM models — the single source of truth for the DB schema.

Tables
------
users           – optional registered accounts (JWT auth)
sessions        – anonymous browser sessions (cookie-based)
documents       – uploaded books/files and their processing status
chunks          – text chunks with pgvector embeddings
queries         – questions asked about a document
llm_usage       – per-call LLM telemetry (tokens, cost, latency)

Design rationale
~~~~~~~~~~~~~~~~
• `documents` has *both* `user_id` (nullable) and `session_id` (nullable).
  Anonymous visitors get a `session_id`; logged-in users get a `user_id`.
  This lets us scope history correctly: "show me my books" queries filter
  on whichever column is non-null.

• `chunks.embedding` is a pgvector `Vector(1536)` column (the
  dimensionality of text-embedding-3-small).  pgvector stores these as
  compact binary, not JSON arrays, so similarity search is efficient.

• `llm_usage` is a separate table (not a column on queries) because one
  user action can trigger many LLM calls (map-reduce summarisation
  produces N map calls + M reduce calls).  Having a dedicated table lets
  us aggregate cost/tokens across any dimension.

• `queries` stores the raw question, the final answer, cited chunk IDs,
  and links back to both the document *and* the LLM usage rows that
  powered it.

• Every table uses UUID primary keys to avoid enumeration attacks and
  make sharding easy later.
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


# ── Base class ────────────────────────────────────────────
class Base(DeclarativeBase):
    """Shared base for all models.  Alembic will detect subclasses."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Users ─────────────────────────────────────────────────
class User(Base):
    """
    Optional registered account.  Anonymous users don't have a row here.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    display_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    documents = relationship("Document", back_populates="user", lazy="selectin")


# ── Sessions (anonymous) ─────────────────────────────────
class Session(Base):
    """
    Browser-session record.  Created automatically on first request when
    no session cookie is present.  Lets anonymous users see their own
    upload history without signing up.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # relationships
    documents = relationship("Document", back_populates="session", lazy="selectin")


# ── Documents ─────────────────────────────────────────────
class Document(Base):
    """
    A single uploaded file.  Tracks ingestion status so the frontend can
    poll for completion, and stores the final summary once ready.

    Status lifecycle:  uploaded → processing → completed | failed
    """
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)

    # ownership — exactly one of these is non-null
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True
    )

    # file metadata
    filename = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)          # "pdf" | "docx"
    file_size_bytes = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)

    # processing
    status = Column(
        SAEnum("uploaded", "processing", "completed", "failed", name="doc_status"),
        default="uploaded",
        nullable=False,
    )
    error_message = Column(Text, nullable=True)             # non-null only when failed

    # output
    summary = Column(Text, nullable=True)                   # final 100-word summary
    chunk_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # relationships
    user = relationship("User", back_populates="documents")
    session = relationship("Session", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    queries = relationship("Query", back_populates="document", cascade="all, delete-orphan")
    llm_usages = relationship("LLMUsage", back_populates="document", cascade="all, delete-orphan")


# ── Chunks ────────────────────────────────────────────────
class Chunk(Base):
    """
    A single text chunk of a document, stored with its embedding.

    The `embedding` column uses pgvector's Vector type for efficient
    cosine / inner-product / L2 similarity search.  We index it with
    an IVFFlat or HNSW index (created in the migration).
    """
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    chunk_index = Column(Integer, nullable=False)            # ordering within the doc
    content = Column(Text, nullable=False)                   # raw text
    page_start = Column(Integer, nullable=True)              # first page this chunk spans
    page_end = Column(Integer, nullable=True)                # last page
    token_count = Column(Integer, nullable=True)

    # pgvector column — 1536 dimensions for text-embedding-3-small
    embedding = Column(Vector(1536), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
    )


# ── Queries ───────────────────────────────────────────────
class Query(Base):
    """
    A question asked about a document, with the generated answer and
    the chunk IDs that were cited.
    """
    __tablename__ = "queries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    # who asked?
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)                     # null until answered
    cited_chunk_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)
    status = Column(
        SAEnum("pending", "completed", "failed", name="query_status"),
        default="pending",
        nullable=False,
    )
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    document = relationship("Document", back_populates="queries")


# ── LLM Usage / Telemetry ────────────────────────────────
class LLMUsage(Base):
    """
    One row per LLM API call.  Captures everything needed for cost
    tracking, latency monitoring, and Langfuse trace correlation.
    """
    __tablename__ = "llm_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    query_id = Column(
        UUID(as_uuid=True), ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )

    # what was called
    operation = Column(String(50), nullable=False)            # e.g. "map_summarize", "reduce", "embed", "rag_answer"
    model = Column(String(100), nullable=False)               # deployment name
    provider = Column(String(20), default="gemini")

    # usage
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)

    # timing
    latency_ms = Column(Integer, nullable=True)

    # tracing
    langfuse_trace_id = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True)           # our internal correlation ID

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    document = relationship("Document", back_populates="llm_usages")

    __table_args__ = (
        Index("ix_llm_usage_document_id", "document_id"),
        Index("ix_llm_usage_created_at", "created_at"),
    )
