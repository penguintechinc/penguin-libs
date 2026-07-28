"""In-memory TokenStore implementation with lazy TTL cleanup."""

import threading
from datetime import UTC, datetime, timedelta

from penguin_aaa.authn.types import Claims


class MemoryTokenStore:
    """
    Thread-safe in-memory token storage.

    Stores refresh tokens, revoked JTIs, and nonces with TTL-based expiry.
    Implements lazy cleanup on read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refresh_tokens: dict[str, tuple[Claims, datetime]] = {}
        self._revoked_jtis: dict[str, datetime] = {}
        self._nonces: dict[str, tuple[str, datetime]] = {}

    def store_refresh(self, token: str, claims: Claims, ttl: timedelta) -> None:
        """Store a refresh token with claims and expiry."""
        with self._lock:
            expiry = datetime.now(UTC) + ttl
            self._refresh_tokens[token] = (claims, expiry)

    def get_claims_for_refresh(self, token: str) -> Claims | None:
        """Retrieve claims for a refresh token, checking expiry and revocation."""
        with self._lock:
            if token not in self._refresh_tokens:
                return None
            claims, expiry = self._refresh_tokens[token]
            if datetime.now(UTC) >= expiry:
                del self._refresh_tokens[token]
                return None
            return claims

    def revoke_refresh(self, token: str) -> None:
        """Revoke a refresh token immediately."""
        with self._lock:
            self._refresh_tokens.pop(token, None)

    def add_revoked_jti(self, jti: str, ttl: timedelta) -> None:
        """Add a JTI to the revocation list."""
        with self._lock:
            expiry = datetime.now(UTC) + ttl
            self._revoked_jtis[jti] = expiry

    def is_jti_revoked(self, jti: str) -> bool:
        """Check if a JTI is revoked (lazy cleanup on read)."""
        with self._lock:
            if jti not in self._revoked_jtis:
                return False
            expiry = self._revoked_jtis[jti]
            if datetime.now(UTC) >= expiry:
                del self._revoked_jtis[jti]
                return False
            return True

    def store_nonce(self, nonce: str, sub: str, ttl: timedelta) -> None:
        """Store a nonce for one-time use."""
        with self._lock:
            expiry = datetime.now(UTC) + ttl
            self._nonces[nonce] = (sub, expiry)

    def consume_nonce(self, nonce: str, sub: str) -> bool:
        """Consume a nonce (one-time use with subject verification)."""
        with self._lock:
            if nonce not in self._nonces:
                return False
            stored_sub, expiry = self._nonces[nonce]
            if datetime.now(UTC) >= expiry:
                del self._nonces[nonce]
                return False
            if stored_sub != sub:
                return False
            del self._nonces[nonce]
            return True
