import threading
from typing import Callable, TypeVar

from .db import query_one

T = TypeVar("T")

_store: dict = {}          # key -> (watermark, payload)
_locks: dict = {}          # key -> threading.Lock
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


def cached(key: str, watermark_sql: str, build: Callable[[], T]) -> T:
    """Serves `build()`'s result from memory for as long as `watermark_sql` hasn't changed - so a screen whose
    build() fans out into many queries can usually answer with one cheap check instead. No TTL and nothing to
    invalidate by hand: the moment the nightly pipeline lands new data, the watermark changes and the very next
    request rebuilds the cache, so "upload files -> pipeline runs -> app updates" keeps working automatically.

    `watermark_sql` must return one row with one column aliased `wm`, e.g.
    "SELECT max(calculation_date) AS wm FROM loan_stage_summary".

    Per-process only: each backend worker process keeps its own copy. Fine for this app's single-process setup;
    would need a shared store (e.g. Redis) if the API is ever run with multiple worker processes.
    """
    row = query_one(watermark_sql)
    watermark = row["wm"] if row else None

    with _lock_for(key):
        if key in _store and _store[key][0] == watermark:
            return _store[key][1]
        payload = build()
        _store[key] = (watermark, payload)
        return payload
