"""Bounded, TTL-based, epoch-checked in-process cache for unwrapped DEKs.

Mirrors the tenant-envelope-encryption design's DEK cache: keyed by
`(tenant_id, dek_version)` so a rotation is a clean cache miss rather than a
version-mismatched decrypt; bounded LRU eviction; a bounded TTL regardless of
rotation activity; an epoch-check callback hook so a caller-supplied
monotonic counter (e.g. a Valkey `INCR tenant-dek-epoch:{tenant_id}`) bounds
staleness to one resolve call even if a pub/sub invalidation is missed; and
an immediate-eviction API for compromise response / KMS access-denied
fail-closed handling. Key material is held internally as a mutable
`bytearray` and zeroed in place on eviction/expiry (`use()`/`get()` still
each return a `bytes` copy for the caller — CPython's `bytes` is immutable,
so once handed out it cannot be zeroed by this cache). **Zeroization is
best-effort, not a security guarantee** — CPython gives no hard guarantee
that no other reference or copy of the key bytes exists (return-value
copies, GC, or memory compaction can all leave copies this cache cannot
reach). Prefer `use()` over `get()` where practical: it passes the key to a
caller-supplied callback for the duration of one call instead of handing
back a `bytes` object the caller might retain longer than necessary.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

_DEFAULT_MAX_SIZE = 1024
_DEFAULT_TTL_SECONDS = 600.0  # 10 minutes, per the design

_T = TypeVar("_T")


@dataclass(slots=True)
class DekCacheEntry:
    """One cached, unwrapped DEK plus the metadata needed to validate it."""

    dek: bytearray
    dek_version: int
    epoch: int
    expires_at: float


@dataclass(slots=True)
class _CacheKey:
    """Composite cache key — dek_version is part of identity, not just a payload field."""

    tenant_id: str
    dek_version: int

    def __hash__(self) -> int:
        """Hash on the (tenant_id, dek_version) pair."""
        return hash((self.tenant_id, self.dek_version))


class DekCache:
    """Bounded LRU cache of unwrapped tenant DEKs, TTL + epoch-checked.

    Not thread-safe by itself — callers running multiple threads/greenlets
    against one instance must hold their own lock around `get`/`put`, same
    as any other in-process mutable cache.
    """

    def __init__(
        self,
        *,
        max_size: int = _DEFAULT_MAX_SIZE,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        epoch_source: Callable[[str], int] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure cache bounds and the optional epoch-check callback.

        Args:
            max_size: Maximum number of (tenant_id, dek_version) entries
                before the least-recently-used entry is evicted.
            ttl_seconds: Bounded lifetime for any entry, independent of
                rotation activity (default 600s, per the design).
            epoch_source: Optional callback returning the current rotation
                epoch for a tenant (e.g. backed by Valkey `GET
                tenant-dek-epoch:{tenant_id}`). When supplied, `get()`
                treats a stored-epoch/current-epoch mismatch as a miss.
            clock: Injectable monotonic clock, for deterministic tests.
        """
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be > 0, got {ttl_seconds}")

        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._epoch_source = epoch_source
        self._clock = clock
        self._entries: OrderedDict[_CacheKey, DekCacheEntry] = OrderedDict()

    def put(self, tenant_id: str, dek_version: int, dek: bytes, *, epoch: int = 0) -> None:
        """Insert/refresh a cached DEK, evicting the LRU entry if at capacity.

        Args:
            tenant_id: Owning tenant (or the platform-identity sentinel).
            dek_version: Version of the DEK being cached.
            dek: Plaintext, unwrapped DEK bytes.
            epoch: The rotation epoch this DEK was resolved under — stored
                alongside the entry for the `epoch_source` comparison on read.
        """
        key = _CacheKey(tenant_id, dek_version)
        if key in self._entries:
            self._evict_key(key)

        if len(self._entries) >= self._max_size:
            lru_key, lru_entry = self._entries.popitem(last=False)
            _zeroize(lru_entry.dek)

        self._entries[key] = DekCacheEntry(
            dek=bytearray(dek),
            dek_version=dek_version,
            epoch=epoch,
            expires_at=self._clock() + self._ttl_seconds,
        )

    def get(self, tenant_id: str, dek_version: int) -> bytes | None:
        """Look up a cached DEK, honoring TTL and (if configured) the epoch check.

        Prefer `use()` where practical — it avoids handing the caller a
        `bytes` copy that outlives the immediate operation. `get()` remains
        available for callers that must hold the key across multiple calls
        (e.g. passing it into another library's API).

        Args:
            tenant_id: Owning tenant.
            dek_version: Version of the DEK to look up.

        Returns:
            The cached plaintext DEK bytes, or None on a miss (not present,
            expired, or epoch-mismatched — all three are indistinguishable
            to the caller, which should re-resolve via KMS on any None).
        """
        entry = self._lookup(tenant_id, dek_version)
        return None if entry is None else bytes(entry.dek)

    def use(self, tenant_id: str, dek_version: int, fn: Callable[[bytes], _T]) -> _T | None:
        """Look up a cached DEK and pass it to `fn`, without the caller holding a copy.

        Reduces (but per the module docstring, cannot eliminate in CPython)
        the lifetime of the plaintext DEK bytes outside this cache — `fn`
        receives the key for the duration of one call and the caller never
        stores a long-lived reference to it directly.

        Args:
            tenant_id: Owning tenant.
            dek_version: Version of the DEK to look up.
            fn: Callback invoked with the plaintext DEK bytes on a hit.

        Returns:
            `fn`'s return value on a cache hit, or None on a miss (same
            miss semantics as `get()` — the caller should re-resolve via
            KMS and `put()` the result).
        """
        entry = self._lookup(tenant_id, dek_version)
        return None if entry is None else fn(bytes(entry.dek))

    def _lookup(self, tenant_id: str, dek_version: int) -> DekCacheEntry | None:
        """Shared hit/miss + TTL/epoch validation logic for `get()` and `use()`."""
        key = _CacheKey(tenant_id, dek_version)
        entry = self._entries.get(key)
        if entry is None:
            return None

        if self._clock() >= entry.expires_at:
            self._evict_key(key)
            return None

        if self._epoch_source is not None:
            current_epoch = self._epoch_source(tenant_id)
            if current_epoch != entry.epoch:
                self._evict_key(key)
                return None

        self._entries.move_to_end(key)
        return entry

    def evict(self, tenant_id: str, dek_version: int | None = None) -> None:
        """Immediately evict cached DEK(s) — rotation, revocation, or KMS access-denied.

        Args:
            tenant_id: Tenant to evict.
            dek_version: If given, evict only that version; otherwise evict
                every cached version for the tenant (used when a rotation's
                exact new version isn't known to the caller triggering eviction).
        """
        if dek_version is not None:
            self._evict_key(_CacheKey(tenant_id, dek_version))
            return

        for key in [k for k in self._entries if k.tenant_id == tenant_id]:
            self._evict_key(key)

    def clear(self) -> None:
        """Evict every cached entry, zeroizing each one best-effort."""
        for key in list(self._entries):
            self._evict_key(key)

    def __len__(self) -> int:
        """Return the current number of cached entries."""
        return len(self._entries)

    def _evict_key(self, key: _CacheKey) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            _zeroize(entry.dek)


def _zeroize(buf: bytearray) -> None:
    """Best-effort in-place zeroization of a key buffer.

    Not a security guarantee — CPython may have produced copies (e.g. via
    `bytes(entry.dek)` on read, GC, or memory compaction) that this cannot
    reach. It removes the one reference this cache definitely controls.
    """
    for i in range(len(buf)):
        buf[i] = 0


__all__ = ["DekCache", "DekCacheEntry"]
