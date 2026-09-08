"""
Pydantic schemas for API request/response bodies.

These are separate from the SQLAlchemy models (db/models.py) because:
  • ORM models define the *database* shape — nullable columns, defaults,
    relationships, etc.
  • Pydantic schemas define the *API contract* — what the frontend sends
    and receives.  They can omit internal fields (hashed_password),
    rename fields, and add validation.

Keeping them separate means we can change the DB schema without breaking
the API, and vice versa.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    database: str


# ── Documents ─────────────────────────────────────────────
class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    summary: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Returned immediately on upload (HTTP 202)."""
    id: uuid.UUID
    status: str = "uploaded"
    message: str = "File accepted. Processing will begin shortly."


# ── Queries ───────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


class ChunkCitation(BaseModel):
    chunk_id: uuid.UUID
    chunk_index: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    content_preview: str = ""


class QueryOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    question: str
    answer: Optional[str] = None
    citations: list[ChunkCitation] = []
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── LLM Usage ────────────────────────────────────────────
class LLMUsageOut(BaseModel):
    id: uuid.UUID
    operation: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Auth ──────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
