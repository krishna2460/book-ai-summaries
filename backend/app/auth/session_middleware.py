"""
Session middleware — automatic anonymous session management.

Every request that doesn't have a session cookie gets one.  This
creates a `sessions` table row and sets a `session_id` cookie.

How it works:
─────────────
1. Incoming request → check for `session_id` cookie
2. If present → validate it exists in DB, update `last_seen_at`
3. If absent → create a new session row, set the cookie
4. Stash session_id on `request.state.session_id` for downstream use

The cookie is:
  • HttpOnly — JS can't read it (XSS protection)
  • SameSite=Lax — sent on same-site navigations (CSRF protection)
  • Secure=False in dev (no HTTPS locally), True in production
  • Max-Age=30 days — sessions expire after 30 days of inactivity
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.db.engine import AsyncSessionLocal
from app.db.models import Session

logger = structlog.get_logger()

COOKIE_NAME = "session_id"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60      # 30 days in seconds


class SessionMiddleware(BaseHTTPMiddleware):
    """Manage anonymous browser sessions via cookies."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        session_id: uuid.UUID | None = None
        is_new_session = False

        # ── Try to read existing cookie ───────────────────
        cookie_value = request.cookies.get(COOKIE_NAME)

        if cookie_value:
            try:
                session_id = uuid.UUID(cookie_value)
            except ValueError:
                session_id = None    # invalid UUID — treat as no cookie

        # ── Validate or create session ────────────────────
        async with AsyncSessionLocal() as db:
            if session_id:
                # Verify session exists in DB
                result = await db.execute(
                    select(Session).where(Session.id == session_id)
                )
                session_row = result.scalar_one_or_none()

                if session_row:
                    # Update last_seen_at
                    session_row.last_seen_at = datetime.now(timezone.utc)
                    await db.commit()
                else:
                    # Cookie has an ID that doesn't exist — create new
                    session_id = None

            if not session_id:
                # Create a new session
                session_id = uuid.uuid4()
                new_session = Session(
                    id=session_id,
                    created_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
                db.add(new_session)
                await db.commit()
                is_new_session = True

                logger.info("new_session_created", session_id=str(session_id))

        # ── Stash on request.state for downstream ─────────
        request.state.session_id = session_id

        # Also bind to structlog so all logs include it
        structlog.contextvars.bind_contextvars(session_id=str(session_id))

        # ── Call downstream ───────────────────────────────
        response = await call_next(request)

        # ── Set cookie if new session ─────────────────────
        if is_new_session:
            response.set_cookie(
                key=COOKIE_NAME,
                value=str(session_id),
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=False,          # set True in production with HTTPS
                path="/",
            )

        return response
