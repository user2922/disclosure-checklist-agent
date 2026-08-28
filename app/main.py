"""FastAPI application: the six routes and nothing else.

No business logic here. Handlers validate, delegate to app.agent and app.audit,
and translate named exceptions into status codes. Anything longer than a dozen
lines belongs in the agent or the engine.
"""

import json
import logging
import traceback
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import audit, blobstore
from app.agent import run_checklist
from app.config import get_settings
from app.errors import (
    DailyCeilingExceeded,
    ModelOutputError,
    ModelUnavailable,
    RateLimitExceeded,
)
from app.schemas import ConfirmRequest, TransactionFacts

logger = logging.getLogger("disclosure_agent")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Prompt 9 replaces these defaults' presentation, not their values: the form
# opens on md_1985_sfh so the first demo beat is one click away.
FORM_DEFAULTS = {
    "jurisdiction": "MD",
    "property_type": "single_family",
    "year_built": 1985,
    "has_association": False,
    "seller_occupancy": "owner_occupied",
    "financing": "conventional",
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Log the model id and mode once at startup. Never the API key."""
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
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def _flush_audit(request: Request, call_next):
    """Buffer audit entries for the request, then write them as one object.

    Only active when a Blob token is configured, i.e. on a serverless host. The
    flush runs in a finally so a failed request still records what it did before
    it failed — an audit log that only captures successes is not an audit log.
    """
    token = get_settings().BLOB_READ_WRITE_TOKEN
    if not token:
        return await call_next(request)
    blobstore.begin_request()
    try:
        return await call_next(request)
    finally:
        blobstore.flush(token)


# --------------------------------------------------------------- error handling


@app.exception_handler(RequestValidationError)
async def _on_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with the offending field names only — never values, never a trace."""
    fields = sorted({str(err["loc"][-1]) for err in exc.errors() if err.get("loc")})
    return JSONResponse(
        status_code=422,
        content={"error": "invalid transaction facts", "fields": fields},
    )


@app.exception_handler(Exception)
async def _on_unhandled(_request: Request, exc: Exception) -> JSONResponse:
    """500 carrying a correlation id and nothing else.

    The traceback goes to the audit log and the server log. Standing Rule 5:
    stack traces, file paths and provider messages never reach a client.
    """
    correlation_id = uuid.uuid4().hex
    logger.exception("unhandled error %s", correlation_id)
    try:
        audit.append(
            "error",
            correlation_id,
            {"stage": "unhandled", "traceback": traceback.format_exc()[-4000:]},
        )
    except Exception:
        logger.exception("audit append failed for %s", correlation_id)
    return JSONResponse(
        status_code=500,
        content={"error": "internal error", "correlation_id": correlation_id},
    )


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    headers = {"Retry-After": "60"} if status == 429 else None
    return JSONResponse(status_code=status, content={"error": message, **extra}, headers=headers)


# --------------------------------------------------------------- routes


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    """The intake form, defaulted so the first demo submit is one click."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"defaults": FORM_DEFAULTS, "result": None, "page": "checklist"},
    )


@app.post("/api/checklist")
async def api_checklist(request: Request) -> Any:
    """Produce a checklist. Accepts JSON or the page's form submission."""
    is_form = "application/x-www-form-urlencoded" in request.headers.get("content-type", "")
    try:
        raw = dict(await request.form()) if is_form else await request.json()
    except Exception:
        return _error(422, "invalid transaction facts", fields=[])

    if is_form:
        raw["has_association"] = str(raw.get("has_association", "")).lower() in {"on", "true", "1"}

    try:
        facts = TransactionFacts.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
        return _error(422, "invalid transaction facts", fields=fields)

    caller = request.client.host if request.client else "unknown"
    try:
        result = run_checklist(facts, caller=caller)
    except (RateLimitExceeded, DailyCeilingExceeded):
        return _error(429, "too many requests; try again shortly")
    except (ModelUnavailable, ModelOutputError):
        return _error(503, "the checklist service is temporarily unavailable")

    if not is_form:
        return JSONResponse(content=json.loads(result.model_dump_json()))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"defaults": raw, "result": result, "page": "checklist"},
    )


@app.post("/api/confirm")
async def api_confirm(request: Request) -> Any:
    """Record a human confirmation. Only the page's button may reach this."""
    settings = get_settings()
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") != settings.APP_URL:
        audit.append("error", "unknown", {"stage": "confirm_origin_rejected", "origin": origin})
        return _error(403, "confirmation must come from the application itself")

    is_form = "application/x-www-form-urlencoded" in request.headers.get("content-type", "")
    try:
        raw = dict(await request.form()) if is_form else await request.json()
        payload = ConfirmRequest.model_validate(raw)
    except Exception:
        return _error(422, "invalid confirmation", fields=["result_id", "confirmed_by"])

    # 404, never 403: a 403 would confirm the result id exists.
    if not audit.result_exists(payload.result_id):
        return _error(404, "no such checklist")

    entry = audit.append(
        "confirmation",
        payload.result_id,
        {"confirmed_by": payload.confirmed_by, "identity_verified": False},
    )
    return JSONResponse(
        content={
            "result_id": payload.result_id,
            "confirmed_by": payload.confirmed_by,
            "confirmed_at": entry.timestamp.isoformat().replace("+00:00", "Z"),
            "identity_verified": False,
        }
    )


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request) -> Any:
    """Human-readable audit log, newest first."""
    read = audit.read_entries(limit=200)
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={"entries": read.entries, "skipped": read.skipped, "page": "audit"},
    )


@app.get("/api/audit")
def api_audit(result_id: str | None = None, limit: int = 200) -> Any:
    """The same entries as JSON, optionally filtered to one result."""
    read = audit.read_entries(limit=max(1, min(limit, 1000)), result_id=result_id)
    return {
        "skipped": read.skipped,
        "entries": [json.loads(e.model_dump_json()) for e in read.entries],
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Reports the configured model id and mode, never the key."""
    settings = get_settings()
    return {"status": "ok", "model": settings.GEMINI_MODEL, "mode": settings.mode}
