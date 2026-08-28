"""FastAPI application entry point.

No business logic lives here. Routes validate input and delegate. At Prompt 2
the only route is /health; Prompt 8 adds the rest.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings

logger = logging.getLogger("disclosure_agent")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Log the model id once at startup, per standing Rule 14.

    Never logs the API key. Settings validation happens here, so a missing
    REQUIRED variable fails the boot rather than the first request.
    """
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    logger.info(
        "starting: model=%s mode=%s audit_log=%s",
        settings.GEMINI_MODEL,
        settings.mode,
        settings.AUDIT_LOG_PATH,
    )
    yield


app = FastAPI(
    title="Disclosure Checklist Agent",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Reports the configured model id, never the key."""
    settings = get_settings()
    return {"status": "ok", "model": settings.GEMINI_MODEL, "mode": settings.mode}
