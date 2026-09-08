"""initial schema — all tables

Revision ID: 0001
Revises: None
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from pgvector.sqlalchemy import Vector

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enable pgvector extension ────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── users ────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── sessions ─────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── doc_status enum ──────────────────────────────────
    doc_status = sa.Enum("uploaded", "processing", "completed", "failed", name="doc_status")

    # ── documents ────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("status", doc_status, default="uploaded", nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── chunks ───────────────────────────────────────────
    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("page_start", sa.Integer, nullable=True),
        sa.Column("page_end", sa.Integer, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    # ── HNSW index for fast ANN search ───────────────────
    # cosine distance is the standard for text-embedding-3-small
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # ── query_status enum ────────────────────────────────
    query_status = sa.Enum("pending", "completed", "failed", name="query_status")

    # ── queries ──────────────────────────────────────────
    op.create_table(
        "queries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("cited_chunk_ids", ARRAY(UUID(as_uuid=True)), default=[]),
        sa.Column("status", query_status, default="pending", nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── llm_usage ────────────────────────────────────────
    op.create_table(
        "llm_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("query_id", UUID(as_uuid=True), sa.ForeignKey("queries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(20), default="azure_openai"),
        sa.Column("prompt_tokens", sa.Integer, default=0),
        sa.Column("completion_tokens", sa.Integer, default=0),
        sa.Column("total_tokens", sa.Integer, default=0),
        sa.Column("estimated_cost_usd", sa.Float, default=0.0),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("langfuse_trace_id", sa.String(100), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_usage_document_id", "llm_usage", ["document_id"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_table("queries")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS doc_status")
    op.execute("DROP TYPE IF EXISTS query_status")
    op.execute("DROP EXTENSION IF EXISTS vector")
