"""Append-only JSONL audit log.

Every rule considered, every model call, every result, every confirmation. The
log is the product's evidence that the agent recommended and a human decided,
so its guarantees are structural rather than conventional:

- the file is only ever opened in append mode, never "w" and never truncated
- a line, once written, is never rewritten or edited
- every entry is validated through AuditEntry before it reaches the file, so a
  malformed entry cannot be persisted
- a corrupt line on read is skipped and counted, never raised — one bad line
  must not take down the audit view, and the count means the damage is visible

KNOWN LIMITATION, and it must be stated in the README and on stage: this writes
to the local filesystem. On Cloud Run that filesystem is ephemeral and the log
does not survive an instance restart. A real deployment writes to Firestore or
a GCS object. Do not imply otherwise in the UI.

Every function takes an optional explicit `path`. That is what lets the test
suite run without any environment configuration at all.
"""

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from app.schemas import AuditEntry, AuditKind, TransactionFacts


class AuditRead(NamedTuple):
    """Entries plus the number of unparseable lines skipped getting them."""

    entries: list[AuditEntry]
    skipped: int


class RuleVerdict(NamedTuple):
    """Minimal shape append_rule_evaluations needs. app.engine.RuleEvaluation fits."""

    rule_id: str
    applies: bool
    tier: str
    review_note: str | None


def _resolve_path(path: str | Path | None) -> Path:
    """Explicit path wins; otherwise fall back to configured settings.

    Settings are imported lazily so that importing this module never requires
    environment configuration.
    """
    if path is not None:
        return Path(path)
    from app.config import get_settings

    return Path(get_settings().AUDIT_LOG_PATH)


def _isoformat_z(moment: datetime) -> str:
    """UTC ISO-8601 with a Z suffix rather than +00:00."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def append(
    kind: AuditKind,
    result_id: str,
    payload: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> AuditEntry:
    """Append one validated entry. Returns the entry that was written.

    Raises before touching the file if the entry is invalid, so a rejected
    entry leaves no trace and no partial line.
    """
    entry = AuditEntry(kind=kind, result_id=result_id, payload=payload)

    record = {
        "timestamp": _isoformat_z(entry.timestamp),
        "kind": entry.kind,
        "result_id": entry.result_id,
        "payload": entry.payload,
    }

    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Mode "a" only. Never "w", never truncate, never seek.
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    return entry


def append_rule_evaluations(
    result_id: str,
    facts: TransactionFacts,
    evaluations: Iterable[RuleVerdict],
    *,
    path: str | Path | None = None,
) -> int:
    """Write one rule_evaluated entry per rule considered — applied or not.

    Logging only the hits would make "every rule the agent evaluated" false.
    Returns the number of entries written.
    """
    facts_hash = facts.canonical_hash()
    written = 0
    for verdict in evaluations:
        append(
            "rule_evaluated",
            result_id,
            {
                "rule_id": verdict.rule_id,
                "applies": bool(verdict.applies),
                "tier": verdict.tier,
                "facts_hash": facts_hash,
            },
            path=path,
        )
        written += 1
    return written


def read_entries(
    limit: int = 200,
    result_id: str | None = None,
    *,
    path: str | Path | None = None,
) -> AuditRead:
    """Return entries newest-first, with the count of lines that would not parse.

    A missing log file is an empty log, not an error — nothing has happened yet.
    """
    target = _resolve_path(path)
    if not target.exists():
        return AuditRead(entries=[], skipped=0)

    entries: list[AuditEntry] = []
    skipped = 0

    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(AuditEntry.model_validate(json.loads(line)))
            except Exception:
                # One bad line must not take down the audit view. It is counted
                # so the corruption is visible rather than silently absorbed.
                skipped += 1

    if result_id is not None:
        entries = [e for e in entries if e.result_id == result_id]

    entries.reverse()
    return AuditRead(entries=entries[:limit], skipped=skipped)


def result_exists(result_id: str, *, path: str | Path | None = None) -> bool:
    """True only if a `result` entry with this id has been written.

    /api/confirm depends on this for its 404. Rule evaluations alone do not
    count: a result that never completed cannot be confirmed.
    """
    read = read_entries(limit=10**9, result_id=result_id, path=path)
    return any(entry.kind == "result" for entry in read.entries)
