"""Vercel Blob backend for the audit log, for serverless deployment.

Why this exists: on Vercel the filesystem is read-only except /tmp, and /tmp is
per-instance and ephemeral. With the file backend, a judge who generates a
checklist on one instance and presses Confirm on another gets 404, and /audit
shows nothing. The audit log is the product's whole claim, so it needs storage
that outlives a single lambda.

Design constraints this satisfies:

- **Append-only, and race-free.** Every blob is written exactly once under a key
  no other write will choose. There is no read-modify-write anywhere, so two
  concurrent requests cannot lose each other's entries — which is the failure a
  single growing object would have.
- **One blob per request, not per entry.** A checklist writes 11 entries; 11
  round trips would add seconds. They are buffered for the life of the request
  and flushed as one object.
- **The result id is in the pathname.** result_exists() and per-result filtering
  are then a single list call, with no need to fetch and parse blob contents.

Pathnames:
    audit/results/<result_id>.jsonl        the batch containing a `result` entry
    audit/events/<ts>-<result_id>-<n>.jsonl  every other batch

API contract, established by probing the live service (api-version 7):
    PUT  https://blob.vercel-storage.com/<pathname>
         Authorization: Bearer <token>, x-api-version: 7,
         x-vercel-blob-access: private
    GET  https://blob.vercel-storage.com/?prefix=<p>        -> {"blobs": [...]}
    GET  <blob url> with the same bearer token              -> the content
Unauthenticated reads of a private blob return 403.
"""

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import httpx

API = "https://blob.vercel-storage.com"
API_VERSION = "7"
RESULTS_PREFIX = "audit/results/"
EVENTS_PREFIX = "audit/events/"

# How many recent blobs /audit will open. The page shows 200 entries and a
# checklist batch holds ~11, so this covers the visible window without fetching
# the entire history on every page load.
MAX_BLOBS_READ = 40

logger = logging.getLogger("disclosure_agent.blob")

# Buffered for the life of one request, then flushed as a single object.
_buffer: ContextVar[list[dict[str, Any]] | None] = ContextVar("audit_buffer", default=None)


def _headers(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "x-api-version": API_VERSION, **extra}


def begin_request() -> None:
    """Start a fresh buffer for this request."""
    _buffer.set([])


def buffer(record: dict[str, Any]) -> None:
    """Hold one already-validated record until the request ends."""
    current = _buffer.get()
    if current is None:
        current = []
        _buffer.set(current)
    current.append(record)


def flush(token: str) -> int:
    """Write the buffered records as one blob. Returns how many were written.

    Never raises into the request path: a failed audit write is logged loudly
    but must not turn a good checklist into a 500 for the user. The failure is
    visible in the server log and by the entry's absence from /audit.
    """
    records = _buffer.get() or []
    _buffer.set([])
    if not records:
        return 0

    result_ids = [r["result_id"] for r in records if r["kind"] == "result"]
    if result_ids:
        pathname = f"{RESULTS_PREFIX}{result_ids[0]}.jsonl"
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        pathname = f"{EVENTS_PREFIX}{stamp}-{records[0]['result_id']}-{uuid.uuid4().hex[:8]}.jsonl"

    body = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records)
    try:
        response = httpx.put(
            f"{API}/{pathname}",
            headers=_headers(
                token,
                **{
                    "x-vercel-blob-access": "private",
                    "x-content-type": "application/x-ndjson",
                    "x-add-random-suffix": "0",
                    "x-allow-overwrite": "1",
                },
            ),
            content=body.encode("utf-8"),
            timeout=15,
        )
        response.raise_for_status()
    except Exception:
        logger.exception("audit flush failed for %s; %d entries lost", pathname, len(records))
        return 0
    return len(records)


def _list(token: str, prefix: str) -> list[dict[str, Any]]:
    response = httpx.get(API, headers=_headers(token), params={"prefix": prefix}, timeout=15)
    response.raise_for_status()
    return response.json().get("blobs", [])


def result_exists(token: str, result_id: str) -> bool:
    """One list call, no content fetch. Backs /api/confirm's 404."""
    try:
        return any(
            b["pathname"] == f"{RESULTS_PREFIX}{result_id}.jsonl"
            for b in _list(token, f"{RESULTS_PREFIX}{result_id}")
        )
    except Exception:
        logger.exception("blob result_exists failed for %s", result_id)
        return False


def read_records(token: str, result_id: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """Return raw records newest-first, plus a count of lines that would not parse."""
    try:
        blobs = _list(token, "audit/")
    except Exception:
        logger.exception("blob listing failed")
        return [], 0

    if result_id is not None:
        blobs = [b for b in blobs if result_id in b["pathname"]]

    blobs.sort(key=lambda b: b.get("uploadedAt", ""), reverse=True)
    blobs = blobs[:MAX_BLOBS_READ]

    records: list[dict[str, Any]] = []
    skipped = 0
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for blob in blobs:
            url = blob.get("downloadUrl") or blob.get("url")
            try:
                text = client.get(url, headers={"Authorization": f"Bearer {token}"}).text
            except Exception:
                logger.exception("blob fetch failed for %s", blob.get("pathname"))
                skipped += 1
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    skipped += 1

    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records, skipped
