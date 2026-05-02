"""Redis-backed TokenStore implementation."""

from datetime import timedelta

import redis

from penguin_aaa.authn.types import Claims


class RedisTokenStore:
    """
    Redis-backed token storage for refresh tokens, revocation lists, and nonces.

    Uses Redis SETEX for TTL management, SADD/SISMEMBER for revocation sets,
    and pipeline operations for atomicity where needed.
    """

    def __init__(self, client: redis.Redis, prefix: str = "penaaa:") -> None:
        """
        Initialize RedisTokenStore.

        Args:
            client: A redis.Redis client instance.
            prefix: Key prefix for all Redis operations (default: "penaaa:").
        """
        self._client = client
        self._prefix = prefix

    def _make_key(self, *parts: str) -> str:
        """Build a Redis key with the configured prefix."""
        return self._prefix + ":".join(parts)

    def store_refresh(self, token: str, claims: Claims, ttl: timedelta) -> None:
        """Store a refresh token with claims and expiry."""
        key = self._make_key("refresh", token)
        ttl_seconds = int(ttl.total_seconds())
        claims_json = claims.model_dump_json()
        self._client.setex(key, ttl_seconds, claims_json)

    def get_claims_for_refresh(self, token: str) -> Claims | None:
        """Retrieve claims for a refresh token, checking revocation."""
        key = self._make_key("refresh", token)
        claims_data = self._client.get(key)
        if claims_data is None:
            return None
        # Check if revoked
        if self.is_jti_revoked(f"refresh:{token}"):
            return None
        if isinstance(claims_data, bytes):
            claims_json = claims_data.decode()
        else:
            claims_json = str(claims_data)
        return Claims.model_validate_json(claims_json)

    def revoke_refresh(self, token: str) -> None:
        """Revoke a refresh token immediately."""
        key = self._make_key("refresh", token)
        self._client.delete(key)

    def add_revoked_jti(self, jti: str, ttl: timedelta) -> None:
        """Add a JTI to the revocation list."""
        key = self._make_key("revoked_jti", jti)
        ttl_seconds = int(ttl.total_seconds())
        self._client.setex(key, ttl_seconds, "1")

    def is_jti_revoked(self, jti: str) -> bool:
        """Check if a JTI is revoked."""
        key = self._make_key("revoked_jti", jti)
        exists_count: int = self._client.exists(key)  # type: ignore
        return exists_count > 0

    def store_nonce(self, nonce: str, sub: str, ttl: timedelta) -> None:
        """Store a nonce for one-time use."""
        key = self._make_key("nonce", nonce)
        ttl_seconds = int(ttl.total_seconds())
        self._client.setex(key, ttl_seconds, sub)

    def consume_nonce(self, nonce: str, sub: str) -> bool:
        """Consume a nonce (one-time use with subject verification)."""
        key = self._make_key("nonce", nonce)
        # Use pipeline for atomic get + delete
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = pipe.execute()
        stored_sub_data = results[0]
        if stored_sub_data is None:
            return False
        if isinstance(stored_sub_data, bytes):
            stored_sub = stored_sub_data.decode()
        else:
            stored_sub = str(stored_sub_data)
        return stored_sub == sub
