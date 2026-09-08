"""
Auth dependencies — FastAPI dependencies for access control.

These dependencies are injected into route handlers to determine WHO
is making the request.  There are three levels:

1. get_current_identity()  — returns (user_id, session_id) tuple.
   At least one is always non-None thanks to the session middleware.
   Logged-in users have user_id set; anonymous users have session_id.

2. require_auth()  — returns the User ORM object.  Raises 401 if
   not logged in.  Used for endpoints that require authentication.

3. get_owner_filter()  — returns a SQLAlchemy WHERE clause that
   scopes queries to the current user's or session's documents.
   This is the key function for access control.

Access control model:
─────────────────────
• Anonymous user (no JWT, has session cookie):
    → can see documents WHERE session_id = their_session_id

• Logged-in user (valid JWT):
    → can see documents WHERE user_id = their_user_id
    → their session's documents are also migrated on login

• No cross-user/cross-session visibility EVER.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_utils import decode_access_token
from app.db.engine import get_db
from app.db.models import Document, User

logger = structlog.get_logger()

# Optional bearer — doesn't fail if no token present
_optional_bearer = HTTPBearer(auto_error=False)


@dataclass
class Identity:
    """Represents the current requester — anonymous or authenticated."""
    user_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


async def get_current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> Identity:
    """Resolve the current requester's identity.

    Checks (in order):
    1. Authorization header → JWT → user_id
    2. Session cookie → session_id (always present via middleware)

    Both can be set simultaneously (logged-in user still has a session).
    """
    user_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = getattr(request.state, "session_id", None)

    # Check JWT if present
    if credentials and credentials.credentials:
        user_id = decode_access_token(credentials.credentials)
        if user_id:
            structlog.contextvars.bind_contextvars(user_id=str(user_id))

    return Identity(user_id=user_id, session_id=session_id)


async def require_auth(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid JWT — raises 401 if not authenticated.

    Returns the full User ORM object for use in the route handler.
    """
    if not identity.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(User).where(User.id == identity.user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Token may be invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_owner_filter(identity: Identity):
    """Build a SQLAlchemy WHERE clause scoping to the current owner.

    This is the CORE access control function.  It ensures:
      • Logged-in users see only their documents
      • Anonymous users see only their session's documents
      • No one ever sees another user's or session's documents

    Returns a SQLAlchemy filter expression to use in queries:
        query = select(Document).where(get_owner_filter(identity))
    """
    conditions = []

    if identity.user_id:
        conditions.append(Document.user_id == identity.user_id)

    if identity.session_id:
        conditions.append(Document.session_id == identity.session_id)

    if not conditions:
        # Should never happen (session middleware guarantees session_id),
        # but fail closed — show nothing.
        logger.warning("no_identity_for_filter")
        return Document.id == None  # noqa: E711 — intentional for SQLAlchemy

    return or_(*conditions)
