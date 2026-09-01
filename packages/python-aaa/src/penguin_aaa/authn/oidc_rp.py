"""OIDC Relying Party — token validation and authorization flow helpers."""

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import jwt
from jwt import PyJWKClient

from penguin_aaa.authn.types import ALLOWED_RP_ALGORITHMS, Claims
from penguin_aaa.hardening.validators import validate_https_url

if TYPE_CHECKING:
    from penguin_aaa.token_store.base import TokenStore


@dataclass(slots=True)
class OIDCRPConfig:
    """Configuration for an OIDC Relying Party."""

    issuer_url: str
    client_id: str
    client_secret: str
    redirect_url: str
    scopes: list[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    clock_skew: timedelta = field(default_factory=lambda: timedelta(seconds=30))

    def __post_init__(self) -> None:
        validate_https_url(self.issuer_url, "issuer_url")
        validate_https_url(self.redirect_url, "redirect_url")
        for alg in self.algorithms:
            if alg not in ALLOWED_RP_ALGORITHMS:
                raise ValueError(
                    f"Algorithm '{alg}' is not allowed. Permitted: {sorted(ALLOWED_RP_ALGORITHMS)}"
                )


class OIDCRelyingParty:
    """
    OIDC Relying Party for validating tokens issued by an external provider.

    Discovers JWKS from the issuer's discovery document, validates tokens,
    and provides helpers for the authorization code flow.

    Args:
        config: Relying party configuration (issuer, client, algorithms).
        token_store: Optional TokenStore consulted after signature validation
            to reject tokens whose jti has been revoked. When None, jti
            revocation is not enforced (no store to check against).
    """

    def __init__(self, config: OIDCRPConfig, token_store: "TokenStore | None" = None) -> None:
        self._config = config
        self._discovery: dict[str, Any] | None = None
        self._jwks_client: PyJWKClient | None = None
        self._token_store = token_store

    async def discover(self) -> dict[str, Any]:
        """
        Fetch and cache the OIDC discovery document from the issuer.

        Returns:
            The parsed discovery document dict.

        Raises:
            httpx.HTTPError: On network or HTTP errors.
            ValueError: If the discovery document is missing required fields
                or advertises a non-HTTPS (non-localhost) jwks_uri.
        """
        if self._discovery is not None:
            return self._discovery

        discovery_url = self._config.issuer_url.rstrip("/") + "/.well-known/openid-configuration"
        async with httpx.AsyncClient() as client:
            response = await client.get(discovery_url, timeout=10.0)
            response.raise_for_status()

        document: dict[str, Any] = response.json()

        required_fields = {"issuer", "jwks_uri", "authorization_endpoint", "token_endpoint"}
        missing = required_fields - set(document.keys())
        if missing:
            raise ValueError(f"Discovery document missing required fields: {missing}")

        validate_https_url(document["jwks_uri"], "jwks_uri")

        self._discovery = document
        self._jwks_client = PyJWKClient(document["jwks_uri"])
        return document

    async def validate_token(self, raw_token: str, expected_nonce: str | None = None) -> Claims:
        """
        Validate a raw JWT token string and return its parsed claims.

        Args:
            raw_token: The encoded JWT string.
            expected_nonce: Optional nonce to verify against id_token payload.

        Returns:
            Validated Claims instance.

        Raises:
            jwt.PyJWTError: On signature, expiry, audience, nonce, or
                revocation-status mismatches.
            ValueError: If required claims are missing or malformed.
        """
        if len(raw_token) > 8192:
            raise ValueError("Token exceeds maximum allowed size of 8192 bytes")

        if self._jwks_client is None:
            await self.discover()

        assert self._jwks_client is not None
        assert self._discovery is not None
        signing_key = self._jwks_client.get_signing_key_from_jwt(raw_token)

        skew_seconds = int(self._config.clock_skew.total_seconds())
        payload = jwt.decode(
            raw_token,
            signing_key.key,
            algorithms=self._config.algorithms,
            audience=self._config.client_id,
            issuer=self._discovery["issuer"],
            leeway=skew_seconds,
        )

        # Reject tokens whose jti has been revoked (e.g. via /oauth2/revoke or
        # /oauth2/introspect-adjacent admin action), even though the signature
        # and standard claims are otherwise valid.
        if self._token_store is not None:
            jti = payload.get("jti")
            if jti and self._token_store.is_jti_revoked(jti):
                raise jwt.InvalidTokenError("Token has been revoked")

        # Verify nonce if expected
        if expected_nonce is not None:
            token_nonce = payload.get("nonce")
            if not hmac.compare_digest(token_nonce or "", expected_nonce):
                raise jwt.PyJWTError("Nonce mismatch")

        # jwt.decode returns dict[str, Any]; normalise before pydantic validation
        _normalise_list_fields(payload, ("aud", "scope", "roles", "teams"))

        # JWT iat/exp are Unix timestamps (int) — convert to datetime for pydantic strict mode
        from datetime import datetime

        for field_name in ("iat", "exp"):
            val = payload.get(field_name)
            if isinstance(val, (int, float)):
                payload[field_name] = datetime.fromtimestamp(val, tz=UTC)

        return Claims.model_validate(payload)

    async def verify_token(self, raw_token: str) -> Claims:
        """Alias for validate_token — the ASGI OIDCAuthMiddleware calls verify_token()."""
        return await self.validate_token(raw_token)

    def validate_state(self, returned_state: str, expected_state: str) -> bool:
        """
        Constant-time comparison of OAuth2 state parameters.

        Args:
            returned_state: The state value received from the redirect.
            expected_state: The state value previously stored by generate_state().

        Returns:
            True only when the two values match.
        """
        return hmac.compare_digest(returned_state, expected_state)

    def generate_state(self) -> str:
        """
        Generate a cryptographically random state token for CSRF protection.

        Returns:
            A URL-safe random string.
        """
        return secrets.token_urlsafe(32)

    def build_authorization_url(
        self,
        state: str,
        nonce: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str = "S256",
    ) -> str:
        """
        Build the authorization redirect URL for the code flow.

        Args:
            state: CSRF state token (from generate_state()).
            nonce: Optional nonce for id_token replay protection.
            code_challenge: Optional PKCE code challenge.
            code_challenge_method: PKCE method ("S256" or "plain"; default "S256").

        Returns:
            The full authorization endpoint URL with query parameters.

        Raises:
            RuntimeError: If discover() has not been called yet.
        """
        if self._discovery is None:
            raise RuntimeError("Call await discover() before building the authorization URL")

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_url,
            "scope": " ".join(self._config.scopes),
            "state": state,
        }
        if nonce is not None:
            params["nonce"] = nonce
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        base: str = self._discovery["authorization_endpoint"]
        return base + "?" + urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate a PKCE (Proof Key for Public Clients) verifier and challenge.

    Returns:
        A tuple of (verifier, challenge_s256) where verifier is 32 random bytes
        base64url-encoded and challenge is the SHA256 hash of the verifier,
        also base64url-encoded.
    """
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalise_list_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    """
    Ensure specified fields in a JWT payload are lists, not bare strings.

    Modifies payload in place.  Space-separated strings (common for scope)
    are split into individual items.
    """
    for key in fields:
        value = payload.get(key)
        if value is None:
            payload[key] = []
        elif isinstance(value, str):
            payload[key] = value.split() if key == "scope" else [value]
