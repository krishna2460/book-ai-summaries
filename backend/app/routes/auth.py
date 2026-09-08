"""
Auth API routes — signup, login, profile, and session migration.

Endpoints:
  POST  /auth/signup           → create account, return JWT
  POST  /auth/login            → verify credentials, return JWT
  GET   /auth/me               → current user profile (requires JWT)
  POST  /auth/migrate-session  → move anonymous docs to logged-in user

Session migration:
  When an anonymous user signs up or logs in, their session's documents
  should transfer to their user account.  The frontend calls
  /auth/migrate-session after receiving the JWT.  This updates
  Document.user_id for all rows matching the session_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Identity, get_current_identity, require_auth
from app.auth.jwt_utils import create_access_token, hash_password, verify_password
from app.db.engine import get_db
from app.db.models import Document, User
from app.schemas import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new user account.

    Returns a JWT immediately so the frontend can switch to
    authenticated mode without a separate login call.

    Error codes:
      409 — email already registered
      422 — validation error (email/password format)
    """
    # Check for duplicate email
    result = await db.execute(
        select(User).where(User.email == body.email.lower().strip())
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Create user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=body.email.lower().strip(),
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    logger.info("user_created", user_id=str(user_id), email=body.email)

    token = create_access_token(user_id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email + password, receive a JWT.

    Error codes:
      401 — invalid credentials
    """
    result = await db.execute(
        select(User).where(User.email == body.email.lower().strip())
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    logger.info("user_logged_in", user_id=str(user.id))

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def get_me(
    user: User = Depends(require_auth),
):
    """Return the current authenticated user's profile.

    Requires a valid JWT in the Authorization header.
    """
    return user


@router.post("/migrate-session", status_code=status.HTTP_200_OK)
async def migrate_session(
    request: Request,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    """Migrate anonymous session documents to the authenticated user.

    Call this after login/signup to transfer any documents uploaded
    anonymously (via session cookie) to the logged-in user's account.

    This ensures continuity — a user who uploads before signing up
    will see their documents after they create an account.
    """
    if not identity.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for session migration.",
        )

    if not identity.session_id:
        return {"migrated": 0, "message": "No session to migrate."}

    # Update all documents belonging to this session to the user
    result = await db.execute(
        update(Document)
        .where(Document.session_id == identity.session_id)
        .where(Document.user_id.is_(None))
        .values(user_id=identity.user_id)
    )

    migrated_count = result.rowcount
    await db.flush()

    logger.info(
        "session_migrated",
        user_id=str(identity.user_id),
        session_id=str(identity.session_id),
        documents_migrated=migrated_count,
    )

    return {
        "migrated": migrated_count,
        "message": f"Migrated {migrated_count} document(s) to your account.",
    }
