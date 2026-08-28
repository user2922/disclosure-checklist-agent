"""Bounded response cache, keyed on the facts hash.

Standing Rule 4 treats caching as a cost control, not an optimisation: the same
transaction facts must never be billed to the provider twice. Only the reason
prose is cached — bucket membership is recomputed every time by the engine,
because that is cheap, deterministic, and the thing we refuse to guess at.
"""

import threading
from collections import OrderedDict

MAX_ENTRIES = 256

_lock = threading.Lock()
_store: OrderedDict[str, dict[str, str]] = OrderedDict()


def get(facts_hash: str) -> dict[str, str] | None:
    """Return the cached rule_id -> reason mapping, or None on a miss."""
    with _lock:
        reasons = _store.get(facts_hash)
        if reasons is None:
            return None
        _store.move_to_end(facts_hash)
        return dict(reasons)


def put(facts_hash: str, reasons: dict[str, str]) -> None:
    """Store a mapping, evicting the least recently used entry past the cap."""
    with _lock:
        _store[facts_hash] = dict(reasons)
        _store.move_to_end(facts_hash)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)


def clear() -> None:
    """Empty the cache. Tests only."""
    with _lock:
        _store.clear()


def size() -> int:
    with _lock:
        return len(_store)
