"""OIDC Provider — token issuance for first-party identity providers."""

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import jwt

from penguin_aaa.authn.types import ALLOWED_PROVIDER_ALGORITHMS, Claims, TokenSet
from penguin_aaa.crypto.keystore import KeyStore
from penguin_aaa.hardening.validators import validate_algorithm, validate_https_url

if TYPE_CHECKING:
    from penguin_aaa.token_store.base import TokenStore


@dataclass(slots=True)
class OIDCProviderConfig:
    """Configuration for a first-party OIDC token provider."""

    issuer: str
    audiences: list[str]
    algorithm: str = "RS256"
    token_ttl: timedelta = field(
        default_factory=lambda: timedelta(minutes=15),
        metadata={
            "description": (
                "Access token TTL. Default 15 minutes for security. "
                "Refresh tokens provide seamless re-authentication. "
                "Should not exceed max_token_ttl."
            )
        },
    )
    max_token_ttl: timedelta = field(default_factory=lambda: timedelta(hours=1))
    refresh_ttl: timedelta = field(default_factory=lambda: timedelta(hours=24))

    def __post_init__(self) -> None:
        validate_https_url(self.issuer, "issuer")
        validate_algorithm(self.algorithm, ALLOWED_PROVIDER_ALGORITHMS)
        if not self.audiences:
            raise ValueError("audiences must contain at least one entry")
        if self.token_ttl > self.max_token_ttl:
            raise ValueError(
                f"token_ttl {self.token_ttl} exceeds max_token_ttl {self.max_token_ttl}"
            )


class OIDCProvider:
    """
    First-party OIDC token provider.

    Issues signed access and id tokens using a managed key store and exposes
    a discovery document for downstream relying parties.
    """

    def __init__(
        self,
        config: OIDCProviderConfig,
        keystore: KeyStore,
        token_store: "TokenStore | None" = None,
    ) -> None:
        self._config = config
        self._keystore = keystore
        self._token_store = token_store

    def issue_token_set(self, claims: Claims, nonce: str | None = None) -> TokenSet:
        """
        Issue a complete TokenSet for the supplied claims.

        The access token and id token are signed JWTs.  The refresh token is
        an opaque random string; callers are responsible for persisting and
        validating it.

        Args:
            claims: Validated claims to embed in the issued tokens.
            nonce: Optional nonce to include in the id_token for replay protection.

        Returns:
            A TokenSet with signed access/id tokens and an opaque refresh token.
        """
        signing_key, kid = self._keystore.get_signing_key()
        now = datetime.now(UTC)
        access_exp = now + self._config.token_ttl
        jti = str(uuid.uuid4())

        base_payload: dict[str, Any] = {
            "sub": claims.sub,
            "iss": self._config.issuer,
            "aud": self._config.audiences,
            "iat": int(now.timestamp()),
            "scope": claims.scope,
            "roles": claims.roles,
            "tenant": claims.tenant,
            "teams": claims.teams,
            "ext": claims.ext,
            "jti": jti,
        }

        access_payload = {**base_payload, "exp": int(access_exp.timestamp()), "token_use": "access"}
        id_payload = {**base_payload, "exp": int(access_exp.timestamp()), "token_use": "id"}
        if nonce is not None:
            id_payload["nonce"] = nonce

        headers = {"kid": kid}

        access_token = jwt.encode(
            access_payload,
            signing_key,
            algorithm=self._config.algorithm,
            headers=headers,
        )
        id_token = jwt.encode(
            id_payload,
            signing_key,
            algorithm=self._config.algorithm,
            headers=headers,
        )

        refresh_token = secrets.token_urlsafe(48)
        expires_in = int(self._config.token_ttl.total_seconds())

        # Store refresh token if token_store is configured
        if self._token_store is not None:
            self._token_store.store_refresh(refresh_token, claims, self._config.refresh_ttl)

        return TokenSet(
            access_token=access_token,
            id_token=id_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    def discovery_document(self) -> dict[str, Any]:
        """
        Return a minimal OIDC discovery document for this provider.

        Returns:
            Dict conforming to the OpenID Connect Discovery 1.0 specification.
        """
        issuer = self._config.issuer.rstrip("/")
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth2/authorize",
            "token_endpoint": f"{issuer}/oauth2/token",
            "userinfo_endpoint": f"{issuer}/oauth2/userinfo",
            "jwks_uri": f"{issuer}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": [self._config.algorithm],
            "scopes_supported": ["openid", "profile", "email"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "claims_supported": [
                "sub",
                "iss",
                "aud",
                "iat",
                "exp",
                "scope",
                "roles",
                "tenant",
                "teams",
            ],
        }

    def jwks(self) -> dict[str, Any]:
        """
        Return the JSON Web Key Set for the active signing keys.

        Returns:
            JWKS dict suitable for serving at the jwks_uri endpoint.
        """
        return self._keystore.get_jwks()

    def refresh(self, refresh_token: str) -> TokenSet:
        """
        Exchange a valid refresh token for a new TokenSet.

        The refresh token is revoked and a new one is issued.

        Args:
            refresh_token: The opaque refresh token to exchange.

        Returns:
            A new TokenSet with rotated refresh token.

        Raises:
            ValueError: If the refresh token is not found, expired, or revoked.
        """
        if self._token_store is None:
            raise ValueError("token_store not configured; refresh not supported")
        claims = self._token_store.get_claims_for_refresh(refresh_token)
        if claims is None:
            raise ValueError("Invalid or expired refresh token")
        self._token_store.revoke_refresh(refresh_token)
        return self.issue_token_set(claims)

    def revoke(self, token: str, token_type_hint: str | None = None) -> None:
        """
        Revoke a token (access or refresh). RFC 7009 compliant.

        Always returns success (200) even if token is already revoked or invalid.

        Args:
            token: The token to revoke (opaque or JWT).
            token_type_hint: Optional hint about token type ("access_token" or "refresh_token").
        """
        if self._token_store is None:
            return
        # If it looks like a refresh token (opaque) or is hinted as such
        if token_type_hint == "refresh_token" or not token.startswith("eyJ"):
            self._token_store.revoke_refresh(token)
        else:
            # It's a JWT; extract jti and revoke
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                jti = payload.get("jti")
                if jti:
                    self._token_store.add_revoked_jti(jti, self._config.token_ttl)
            except jwt.PyJWTError:
                pass  # Invalid token; silently ignore per RFC 7009

    def introspect(self, token: str) -> dict[str, Any]:
        """
        Return token introspection data. RFC 7662 compliant.

        Returns {"active": False} for invalid tokens, {"active": True, ...} for valid tokens.

        Args:
            token: The token to introspect (opaque or JWT).

        Returns:
            A dict with introspection result.
        """
        # Try JWT first
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            jti = payload.get("jti")
            if jti and self._token_store and self._token_store.is_jti_revoked(jti):
                return {"active": False}
            return {
                "active": True,
                "sub": payload.get("sub"),
                "exp": payload.get("exp"),
                "scope": " ".join(payload.get("scope", [])),
                "tenant": payload.get("tenant"),
                "aud": payload.get("aud"),
                "iss": payload.get("iss"),
            }
        except jwt.PyJWTError:
            pass
        # Try as refresh token
        if self._token_store is not None:
            claims = self._token_store.get_claims_for_refresh(token)
            if claims is not None:
                return {
                    "active": True,
                    "sub": claims.sub,
                    "scope": " ".join(claims.scope),
                    "tenant": claims.tenant,
                }
        return {"active": False}
