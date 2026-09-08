"""
Observability setup — initializes Langfuse if keys are present.
"""

import structlog
from langfuse import Langfuse
from app.config import settings

logger = structlog.get_logger()

langfuse_client = None

if settings.langfuse_public_key and settings.langfuse_secret_key:
    try:
        langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host
        )
        logger.info("langfuse_initialized")
    except Exception as e:
        logger.warning("langfuse_init_failed", error=str(e))
else:
    logger.info("langfuse_disabled_missing_keys")

def get_langfuse() -> Langfuse | None:
    return langfuse_client
