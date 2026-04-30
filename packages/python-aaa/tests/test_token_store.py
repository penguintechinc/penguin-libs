"""Tests for TokenStore implementations (memory and redis)."""

from datetime import UTC, datetime, timedelta

from penguin_aaa.authn.types import Claims
from penguin_aaa.token_store.memory import MemoryTokenStore


def _make_claims() -> Claims:
    now = datetime.now(UTC)
    return Claims.model_validate({
        "sub": "user-123",
        "iss": "https://auth.example.com",
        "aud": ["api.example.com"],
        "iat": now,
        "exp": now + timedelta(hours=1),
        "scope": ["openid", "profile"],
        "roles": ["user"],
        "tenant": "acme",
        "teams": ["eng"],
    })


class TestMemoryTokenStore:
    def test_store_and_get_refresh_token(self) -> None:
        store = MemoryTokenStore()
        claims = _make_claims()
        token = "refresh-token-xyz"
        ttl = timedelta(hours=24)

        store.store_refresh(token, claims, ttl)
        retrieved = store.get_claims_for_refresh(token)

        assert retrieved is not None
        assert retrieved.sub == claims.sub

    def test_get_nonexistent_refresh_token(self) -> None:
        store = MemoryTokenStore()
        retrieved = store.get_claims_for_refresh("nonexistent")
        assert retrieved is None

    def test_refresh_token_expiry(self) -> None:
        store = MemoryTokenStore()
        claims = _make_claims()
        token = "short-lived-token"
        ttl = timedelta(seconds=0)

        store.store_refresh(token, claims, ttl)
        # Token should be expired immediately
        import time
        time.sleep(0.01)
        retrieved = store.get_claims_for_refresh(token)
        assert retrieved is None

    def test_revoke_refresh_token(self) -> None:
        store = MemoryTokenStore()
        claims = _make_claims()
        token = "token-to-revoke"

        store.store_refresh(token, claims, timedelta(hours=24))
        store.revoke_refresh(token)
        retrieved = store.get_claims_for_refresh(token)
        assert retrieved is None

    def test_add_and_check_revoked_jti(self) -> None:
        store = MemoryTokenStore()
        jti = "jti-12345"
        ttl = timedelta(hours=1)

        store.add_revoked_jti(jti, ttl)
        assert store.is_jti_revoked(jti) is True

    def test_jti_expiry(self) -> None:
        store = MemoryTokenStore()
        jti = "short-lived-jti"
        ttl = timedelta(seconds=0)

        store.add_revoked_jti(jti, ttl)
        import time
        time.sleep(0.01)
        assert store.is_jti_revoked(jti) is False

    def test_jti_not_revoked(self) -> None:
        store = MemoryTokenStore()
        assert store.is_jti_revoked("nonexistent-jti") is False

    def test_store_and_consume_nonce(self) -> None:
        store = MemoryTokenStore()
        nonce = "nonce-abc123"
        sub = "user-456"
        ttl = timedelta(minutes=5)

        store.store_nonce(nonce, sub, ttl)
        result = store.consume_nonce(nonce, sub)
        assert result is True

    def test_consume_nonce_deletes_it(self) -> None:
        store = MemoryTokenStore()
        nonce = "nonce-delete-test"
        sub = "user-789"

        store.store_nonce(nonce, sub, timedelta(minutes=5))
        store.consume_nonce(nonce, sub)
        # Consuming again should fail
        result = store.consume_nonce(nonce, sub)
        assert result is False

    def test_consume_nonce_wrong_subject(self) -> None:
        store = MemoryTokenStore()
        nonce = "nonce-wrong-sub"
        sub1 = "user-100"
        sub2 = "user-200"

        store.store_nonce(nonce, sub1, timedelta(minutes=5))
        result = store.consume_nonce(nonce, sub2)
        assert result is False

    def test_consume_nonexistent_nonce(self) -> None:
        store = MemoryTokenStore()
        result = store.consume_nonce("nonexistent", "user-999")
        assert result is False

    def test_nonce_expiry(self) -> None:
        store = MemoryTokenStore()
        nonce = "short-nonce"
        sub = "user-exp"
        ttl = timedelta(seconds=0)

        store.store_nonce(nonce, sub, ttl)
        import time
        time.sleep(0.01)
        result = store.consume_nonce(nonce, sub)
        assert result is False

    def test_thread_safety(self) -> None:
        """Test concurrent access to the token store."""
        import threading

        store = MemoryTokenStore()
        claims = _make_claims()
        results: list[bool] = []

        def add_and_get(token_id: str) -> None:
            token = f"token-{token_id}"
            store.store_refresh(token, claims, timedelta(hours=1))
            retrieved = store.get_claims_for_refresh(token)
            results.append(retrieved is not None)

        threads = [threading.Thread(target=add_and_get, args=(str(i),)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        assert len(results) == 10
