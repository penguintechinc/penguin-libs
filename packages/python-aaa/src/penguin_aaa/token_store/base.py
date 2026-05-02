"""TokenStore protocol for refresh token, JTI revocation, and nonce storage."""

from datetime import timedelta
from typing import Protocol, runtime_checkable

from penguin_aaa.authn.types import Claims


@runtime_checkable
class TokenStore(Protocol):
    """Protocol for token storage backends (refresh tokens, revocation, nonces)."""

    def store_refresh(self, token: str, claims: Claims, ttl: timedelta) -> None:
        """
        Store a refresh token with associated claims and expiry.

        Args:
            token: The opaque refresh token string.
            claims: The Claims to associate with the token.
            ttl: Time-to-live for the token (used to compute expiry).
        """
        ...

    def get_claims_for_refresh(self, token: str) -> Claims | None:
        """
        Retrieve claims for a refresh token.

        Returns None if the token is not found, expired, or revoked.

        Args:
            token: The opaque refresh token string.

        Returns:
            The Claims if the token is valid, None if not found/expired/revoked.
        """
        ...

    def revoke_refresh(self, token: str) -> None:
        """
        Revoke a refresh token immediately.

        Args:
            token: The opaque refresh token string to revoke.
        """
        ...

    def add_revoked_jti(self, jti: str, ttl: timedelta) -> None:
        """
        Add a JWT ID (jti) to the revocation list.

        Args:
            jti: The JWT ID claim value.
            ttl: Time-to-live for the revocation entry.
        """
        ...

    def is_jti_revoked(self, jti: str) -> bool:
        """
        Check if a JWT ID (jti) is revoked.

        Args:
            jti: The JWT ID claim value.

        Returns:
            True if revoked, False otherwise.
        """
        ...

    def store_nonce(self, nonce: str, sub: str, ttl: timedelta) -> None:
        """
        Store a nonce for one-time use.

        Args:
            nonce: The nonce value.
            sub: The subject (user ID) associated with the nonce.
            ttl: Time-to-live for the nonce.
        """
        ...

    def consume_nonce(self, nonce: str, sub: str) -> bool:
        """
        Consume a nonce (one-time use).

        The nonce must exist, not be expired, and the subject must match.
        If valid, the nonce is deleted and True is returned.
        If invalid or already consumed, False is returned.

        Args:
            nonce: The nonce value.
            sub: The subject (user ID) to verify against stored value.

        Returns:
            True if the nonce was valid and consumed, False otherwise.
        """
        ...
