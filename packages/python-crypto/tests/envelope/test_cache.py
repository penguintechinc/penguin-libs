"""Tests for the bounded/TTL/epoch-checked DEK cache."""

import pytest

from penguin_crypto.envelope.cache import DekCache


class _FakeClock:
    """Deterministic, manually-advanced clock for TTL tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_put_then_get_round_trip() -> None:
    """A cached DEK is returned as-is on a hit."""
    cache = DekCache()
    cache.put("tenant-a", 1, b"\x00" * 32)
    assert cache.get("tenant-a", 1) == b"\x00" * 32


def test_get_miss_on_unknown_key() -> None:
    """Looking up a tenant/version never cached returns None, not an exception."""
    cache = DekCache()
    assert cache.get("tenant-a", 1) is None


def test_cache_key_includes_dek_version() -> None:
    """A rotation (new dek_version) is a clean miss, never a version-mismatched decrypt."""
    cache = DekCache()
    cache.put("tenant-a", 1, b"\x01" * 32)
    assert cache.get("tenant-a", 2) is None
    assert cache.get("tenant-a", 1) == b"\x01" * 32


def test_ttl_expiry() -> None:
    """An entry past its TTL is treated as a miss and evicted."""
    clock = _FakeClock()
    cache = DekCache(ttl_seconds=10, clock=clock)
    cache.put("tenant-a", 1, b"\x02" * 32)

    clock.advance(9)
    assert cache.get("tenant-a", 1) == b"\x02" * 32  # still fresh

    clock.advance(2)  # total 11s > 10s TTL
    assert cache.get("tenant-a", 1) is None
    assert len(cache) == 0


def test_bounded_lru_evicts_least_recently_used() -> None:
    """At capacity, inserting a new entry evicts the least-recently-used one."""
    cache = DekCache(max_size=2)
    cache.put("tenant-a", 1, b"\x01" * 32)
    cache.put("tenant-b", 1, b"\x02" * 32)

    # Touch tenant-a so tenant-b becomes the LRU entry.
    cache.get("tenant-a", 1)

    cache.put("tenant-c", 1, b"\x03" * 32)  # should evict tenant-b, not tenant-a

    assert cache.get("tenant-a", 1) == b"\x01" * 32
    assert cache.get("tenant-b", 1) is None
    assert cache.get("tenant-c", 1) == b"\x03" * 32


def test_epoch_mismatch_forces_a_miss() -> None:
    """A caller-supplied epoch source bounds staleness to one resolve call.

    Bounds a missed pub/sub rotation event: even with a fresh TTL, a bumped
    epoch (rotation happened) forces a re-resolve on the very next cache use.
    """
    current_epoch = {"tenant-a": 1}
    cache = DekCache(epoch_source=lambda tenant_id: current_epoch[tenant_id])

    cache.put("tenant-a", 1, b"\x04" * 32, epoch=1)
    assert cache.get("tenant-a", 1) == b"\x04" * 32

    current_epoch["tenant-a"] = 2  # rotation happened; pub/sub event assumed missed
    assert cache.get("tenant-a", 1) is None


def test_epoch_match_is_a_hit() -> None:
    """When the epoch source agrees with the stored epoch, the cache still serves the hit."""
    cache = DekCache(epoch_source=lambda tenant_id: 5)
    cache.put("tenant-a", 1, b"\x05" * 32, epoch=5)
    assert cache.get("tenant-a", 1) == b"\x05" * 32


def test_immediate_eviction_single_version() -> None:
    """The eviction API removes a specific tenant/version pair immediately."""
    cache = DekCache()
    cache.put("tenant-a", 1, b"\x06" * 32)
    cache.put("tenant-a", 2, b"\x07" * 32)

    cache.evict("tenant-a", 1)

    assert cache.get("tenant-a", 1) is None
    assert cache.get("tenant-a", 2) == b"\x07" * 32


def test_immediate_eviction_all_versions_for_tenant() -> None:
    """Evicting without a dek_version clears every cached version for that tenant.

    Used for KMS permission-denied fail-closed handling, where the caller
    doesn't necessarily know which version(s) are cached.
    """
    cache = DekCache()
    cache.put("tenant-a", 1, b"\x08" * 32)
    cache.put("tenant-a", 2, b"\x09" * 32)
    cache.put("tenant-b", 1, b"\x0a" * 32)

    cache.evict("tenant-a")

    assert cache.get("tenant-a", 1) is None
    assert cache.get("tenant-a", 2) is None
    assert cache.get("tenant-b", 1) == b"\x0a" * 32  # unaffected


def test_clear_evicts_everything() -> None:
    """clear() empties the cache entirely."""
    cache = DekCache()
    cache.put("tenant-a", 1, b"\x0b" * 32)
    cache.put("tenant-b", 1, b"\x0c" * 32)
    cache.clear()
    assert len(cache) == 0


def test_evicted_entry_is_zeroized_best_effort() -> None:
    """Evicting a DEK overwrites its internal buffer rather than leaving it intact."""
    cache = DekCache()
    cache.put("tenant-a", 1, b"\xff" * 32)
    key = next(iter(cache._entries))  # noqa: SLF001 - inspecting internal state deliberately
    entry = cache._entries[key]  # noqa: SLF001
    cache.evict("tenant-a", 1)
    assert bytes(entry.dek) == b"\x00" * 32


def test_rejects_invalid_max_size() -> None:
    """A cache that can hold zero entries is a configuration bug."""
    with pytest.raises(ValueError, match="max_size"):
        DekCache(max_size=0)


def test_rejects_invalid_ttl() -> None:
    """A non-positive TTL would mean every entry is immediately expired."""
    with pytest.raises(ValueError, match="ttl_seconds"):
        DekCache(ttl_seconds=0)
