"""Rate limiting and the daily spend ceiling. Both fail closed.

Standing Rule 4: a metered API without limits is not allowed to be called.
Fail closed means that if the limiter itself malfunctions the request is
blocked, never allowed. An open failure on a paid API turns a bug into a bill.

In-process state, which is the right scale for a single-instance demo and
explicitly not the right scale for a multi-instance deployment — that would
need shared state in Redis. Said plainly rather than left implied.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from app.errors import DailyCeilingExceeded, RateLimitExceeded

_WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_daily_count = 0
_daily_date: str = ""


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def check_rate_limit(caller: str, limit_per_minute: int) -> None:
    """Allow or block one caller. Raises RateLimitExceeded when over the limit.

    Any internal failure blocks rather than allows.
    """
    try:
        now = time.monotonic()
        with _lock:
            bucket = _hits[caller]
            while bucket and now - bucket[0] >= _WINDOW_SECONDS:
                bucket.popleft()
            if len(bucket) >= limit_per_minute:
                raise RateLimitExceeded(f"rate limit of {limit_per_minute}/min exceeded")
            bucket.append(now)
    except RateLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate: fail closed on any fault
        raise RateLimitExceeded("rate limiter unavailable; refusing the request") from exc


def check_daily_ceiling(max_per_day: int) -> None:
    """Raise DailyCeilingExceeded once the process has spent its daily budget.

    Checked before every model call and *not* incremented here — see
    record_model_call. Cached and offline responses must not consume budget.
    """
    try:
        with _lock:
            global _daily_count, _daily_date
            today = _today()
            if today != _daily_date:
                _daily_date = today
                _daily_count = 0
            if _daily_count >= max_per_day:
                raise DailyCeilingExceeded(f"daily ceiling of {max_per_day} model calls reached")
    except DailyCeilingExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate: fail closed on any fault
        raise DailyCeilingExceeded("ceiling check unavailable; refusing the request") from exc


def record_model_call() -> None:
    """Count one call that actually reached the provider."""
    with _lock:
        global _daily_count, _daily_date
        today = _today()
        if today != _daily_date:
            _daily_date = today
            _daily_count = 0
        _daily_count += 1


def reset_for_tests() -> None:
    """Clear all limiter state. Tests only."""
    with _lock:
        global _daily_count, _daily_date
        _hits.clear()
        _daily_count = 0
        _daily_date = ""


def snapshot() -> dict[str, int]:
    """Current counters, for diagnostics and tests."""
    with _lock:
        return {"callers_tracked": len(_hits), "model_calls_today": _daily_count}
