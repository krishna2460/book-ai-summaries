"""
Document API routes — upload, status polling, and document listing.

Endpoints:
  POST   /documents/upload     → upload a file, start async processing
  GET    /documents/{id}       → get document status/summary
  GET    /documents/{id}/status → lightweight status poll

These routes will be extended in Step 7 (auth, history).  For now,
document ownership uses a session_id query parameter as a placeholder.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_db
from app.db.models import Document
from app.ingestion import SUPPORTED_TYPES
from app.schemas import DocumentOut, DocumentUploadResponse
from app.tasks.document_processor import process_document
from app.auth.dependencies import Identity, get_current_identity, get_owner_filter

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])

# Max upload size: 100 MB
MAX_FILE_SIZE = 100 * 1024 * 1024


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF or DOCX file for summarization.

    Returns HTTP 202 immediately — processing runs in the background.
    Poll GET /documents/{id} or /documents/{id}/status to track progress.

    Error codes:
      422 — unsupported file type or empty file
      413 — file too large (>100 MB)
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── Validate file type ────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Filename is required.",
        )

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: '.{extension}'. Supported: {', '.join(sorted(SUPPORTED_TYPES))}",
        )

    # ── Read file bytes ───────────────────────────────────
    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)} MB.",
        )

    # ── Create document record ────────────────────────────
    doc_id = uuid.uuid4()

    doc = Document(
        id=doc_id,
        user_id=identity.user_id,
        session_id=identity.session_id,
        filename=file.filename,
        file_type=extension,
        file_size_bytes=len(file_bytes),
        status="uploaded",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    await db.flush()

    logger.info(
        "document_uploaded",
        document_id=str(doc_id),
        filename=file.filename,
        file_type=extension,
        size_bytes=len(file_bytes),
    )

    # ── Save file to disk (for potential re-processing) ──
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{doc_id}.{extension}")

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # ── Kick off background processing ────────────────────
    # asyncio.create_task runs the coroutine concurrently.
    # The HTTP response is sent immediately with 202.
    asyncio.create_task(
        process_document(
            document_id=doc_id,
            file_bytes=file_bytes,
            file_type=extension,
            request_id=request_id,
        )
    )

    return DocumentUploadResponse(
        id=doc_id,
        status="uploaded",
        message="File accepted. Processing will begin shortly.",
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a document's current status, summary, and metadata.

    Used by the frontend to poll for processing completion.

    Error codes:
      404 — document not found
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return doc


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Lightweight status endpoint for polling.

    Returns only status and error_message — cheaper than fetching
    the full document with summary text.
    """
    result = await db.execute(
        select(Document.status, Document.error_message)
        .where(Document.id == document_id)
    )
    row = result.one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return {
        "document_id": str(document_id),
        "status": row.status,
        "error_message": row.error_message,
    }


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    """List all documents belonging to the current user or session.

    Returns documents in reverse chronological order (newest first).
    Access is scoped by identity — users only see their own documents.
    """
    owner_filter = get_owner_filter(identity)
    result = await db.execute(
        select(Document)
        .where(owner_filter)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return docs
