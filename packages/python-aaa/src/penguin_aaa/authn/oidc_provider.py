"""OIDC Provider — token issuance for first-party identity providers."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from penguin_aaa.authn.types import ALLOWED_PROVIDER_ALGORITHMS, Claims, TokenSet
from penguin_aaa.crypto.keystore import KeyStore
from penguin_aaa.hardening.validators import validate_algorithm, validate_https_url


@dataclass(slots=True)
class OIDCProviderConfig:
    """Configuration for a first-party OIDC token provider."""

    issuer: str
    audiences: list[str]
    algorithm: str = "RS256"
    token_ttl: timedelta = field(default_factory=lambda: timedelta(hours=1))
    refresh_ttl: timedelta = field(default_factory=lambda: timedelta(hours=24))

    def __post_init__(self) -> None:
        validate_https_url(self.issuer, "issuer")
        validate_algorithm(self.algorithm, ALLOWED_PROVIDER_ALGORITHMS)
        if not self.audiences:
            raise ValueError("audiences must contain at least one entry")


class OIDCProvider:
    """
    First-party OIDC token provider.

    Issues signed access and id tokens using a managed key store and exposes
    a discovery document for downstream relying parties.
    """

    def __init__(self, config: OIDCProviderConfig, keystore: KeyStore) -> None:
        self._config = config
        self._keystore = keystore

    def issue_token_set(self, claims: Claims) -> TokenSet:
        """
        Issue a complete TokenSet for the supplied claims.

        The access token and id token are signed JWTs.  The refresh token is
        an opaque random string; callers are responsible for persisting and
        validating it.

        Args:
            claims: Validated claims to embed in the issued tokens.

        Returns:
            A TokenSet with signed access/id tokens and an opaque refresh token.
        """
        signing_key, kid = self._keystore.get_signing_key()
        now = datetime.now(timezone.utc)
        access_exp = now + self._config.token_ttl

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
        }

        access_payload = {**base_payload, "exp": int(access_exp.timestamp()), "token_use": "access"}
        id_payload = {**base_payload, "exp": int(access_exp.timestamp()), "token_use": "id"}

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
                "sub", "iss", "aud", "iat", "exp",
                "scope", "roles", "tenant", "teams",
            ],
        }

    def jwks(self) -> dict[str, Any]:
        """
        Return the JSON Web Key Set for the active signing keys.

        Returns:
            JWKS dict suitable for serving at the jwks_uri endpoint.
        """
        return self._keystore.get_jwks()
