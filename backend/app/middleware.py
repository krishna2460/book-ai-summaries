"""
FastAPI middleware for request-ID propagation and request logging.

Every inbound request gets a unique `request_id` (UUID). This ID is:
  1. Bound to structlog's contextvars → all log lines within the request
     automatically include it.
  2. Returned in the `X-Request-ID` response header → the frontend or
     any caller can correlate errors with backend logs.
  3. Used later as the correlation key in LLM usage rows and Langfuse traces.

Why middleware instead of a dependency?
───────────────────────────────────────
Middleware runs *before* route matching, so even 404s and framework-level
errors get a request_id and timing log.  A dependency only fires after
a route is matched.
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request_id to every request and log it."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())

        # Bind to structlog contextvars — every logger.info() etc.
        # in downstream code will include this automatically
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Also stash on request.state so dependencies can read it
        request.state.request_id = request_id

        start = time.perf_counter()

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params) if request.query_params else None,
        )

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed")
            raise

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request_completed",
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )

        response.headers["X-Request-ID"] = request_id
        return response
