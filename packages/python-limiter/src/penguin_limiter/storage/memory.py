"""Thread-safe in-memory storage backend.

Suitable for single-process deployments and testing.  Uses a ``threading.Lock``
per key to minimise contention, with a global lock only for key creation.

The store is intentionally *not* shared across processes — use
:class:`~penguin_limiter.storage.redis_store.RedisStorage` for multi-instance
deployments.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Counter:
    value: int = 0
    expires_at: float = 0.0


@dataclass(slots=True)
class _TokenState:
    tokens: float = 0.0
    last_refill: float = 0.0
    expires_at: float = 0.0


class MemoryStorage:
    """In-memory rate-limit storage with per-key TTL expiry.

    All operations are O(1) for fixed-window counters and O(n) for sliding-
    window timestamp logs (where n is the window length in requests).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, _Counter] = {}
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._ts_locks: dict[str, threading.Lock] = {}
        self._token_states: dict[str, _TokenState] = {}
        self._tok_locks: dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------
    # Fixed-window helpers
    # ------------------------------------------------------------------

    def increment(self, key: str, window: int) -> int:
        """Atomically increment the fixed-window counter for *key*."""
        now = time.time()
        with self._lock:
            counter = self._counters.get(key)
            if counter is None or now >= counter.expires_at:
                counter = _Counter(value=1, expires_at=now + window)
                self._counters[key] = counter
            else:
                counter.value += 1
            return counter.value

    def get(self, key: str) -> int:
        """Return current fixed-window count (0 if expired or absent)."""
        now = time.time()
        with self._lock:
            counter = self._counters.get(key)
            if counter is None or now >= counter.expires_at:
                return 0
            return counter.value

    # ------------------------------------------------------------------
    # Sliding-window helpers
    # ------------------------------------------------------------------

    def _ts_lock(self, key: str) -> threading.Lock:
        with self._lock:
            if key not in self._ts_locks:
                self._ts_locks[key] = threading.Lock()
            return self._ts_locks[key]

    def get_timestamps(self, key: str) -> list[float]:
        """Return a *copy* of the timestamp list for *key*."""
        with self._ts_lock(key):
            return list(self._timestamps[key])

    def add_timestamp(self, key: str, ts: float, window: int) -> int:
        """Append *ts*, prune entries older than *window* seconds, return count."""
        cutoff = ts - window
        with self._ts_lock(key):
            lst = self._timestamps[key]
            lst.append(ts)
            # Prune expired entries in-place (list is roughly sorted by insertion)
            while lst and lst[0] < cutoff:
                lst.pop(0)
            return len(lst)

    # ------------------------------------------------------------------
    # Token-bucket helpers
    # ------------------------------------------------------------------

    def _tok_lock(self, key: str) -> threading.Lock:
        with self._lock:
            if key not in self._tok_locks:
                self._tok_locks[key] = threading.Lock()
            return self._tok_locks[key]

    def get_token_state(self, key: str) -> tuple[float, float]:
        """Return ``(tokens, last_refill_time)``; ``(-1, 0)`` if not set."""
        now = time.time()
        with self._tok_lock(key):
            state = self._token_states.get(key)
            if state is None or now >= state.expires_at:
                return -1.0, 0.0
            return state.tokens, state.last_refill

    def set_token_state(self, key: str, tokens: float, ts: float, ttl: int) -> None:
        """Persist token-bucket state for *key*."""
        with self._tok_lock(key):
            self._token_states[key] = _TokenState(
                tokens=tokens,
                last_refill=ts,
                expires_at=ts + ttl,
            )

    def ping(self) -> bool:
        """Always returns ``True`` — memory storage is always available."""
        return True
