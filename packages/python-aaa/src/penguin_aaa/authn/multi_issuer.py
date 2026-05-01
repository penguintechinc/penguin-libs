"""Multi-issuer OIDC RP — accepts tokens from multiple configured providers.

Supports external IdPs like Okta, SkausWatch, and internal providers.
"""

from dataclasses import dataclass, field
from typing import Any

import jwt as pyjwt

from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, OIDCRPConfig
from penguin_aaa.authn.types import Claims


@dataclass(slots=True)
class ClaimsMapping:
    """Maps external provider claim names to internal Claims field names."""

    sub_claim: str = "sub"
    iss_claim: str = "iss"
    tenant_claim: str = "tenant"  # e.g. Okta uses "tid" or custom, SkausWatch uses "tenant"
    roles_claim: str = "roles"  # e.g. Okta uses "groups"
    teams_claim: str = "teams"
    scope_claim: str = "scope"
    ext_passthrough: bool = True  # Pass all unmapped claims into Claims.ext


@dataclass(slots=True)
class UpstreamProvider:
    """Configuration for a single upstream OIDC provider."""

    name: str  # Human-readable name e.g. "okta", "skauswatch"
    config: OIDCRPConfig
    claims_mapping: ClaimsMapping = field(default_factory=ClaimsMapping)


class MultiIssuerRelyingParty:
    """
    Validates tokens from multiple upstream OIDC providers.

    Each incoming token's `iss` claim is matched to the corresponding configured
    provider. If no provider matches the issuer, validation fails.

    Use this when services accept tokens from external IdPs (Okta, SkausWatch)
    in addition to (or instead of) internally issued tokens.
    """

    def __init__(self, providers: list[UpstreamProvider]) -> None:
        if not providers:
            raise ValueError("At least one upstream provider must be configured")
        self._providers = providers
        self._rps: dict[str, OIDCRelyingParty] = {}  # issuer_url → RP

    async def discover_all(self) -> None:
        """Discover OIDC configuration for all configured providers."""
        for provider in self._providers:
            rp = OIDCRelyingParty(provider.config)
            await rp.discover()
            self._rps[provider.config.issuer_url.rstrip("/")] = rp

    async def validate_token(self, raw_token: str, expected_nonce: str | None = None) -> Claims:
        """
        Validate a token from any configured upstream provider.

        Extracts the issuer from the unverified header, finds the matching RP,
        then performs full validation. Returns mapped Claims on success.

        Args:
            raw_token: The encoded JWT token string.
            expected_nonce: Optional nonce to verify against id_token payload.

        Returns:
            Validated Claims instance with claims mapped from provider format.

        Raises:
            ValueError: If the issuer is not from a known provider.
            jwt.PyJWTError: If the token is invalid.
        """
        # Decode header only (no verification) to get issuer for routing
        try:
            unverified = pyjwt.decode(raw_token, options={"verify_signature": False})
            issuer = unverified.get("iss", "").rstrip("/")
        except Exception as exc:
            raise ValueError(f"Cannot decode token header: {exc}") from exc

        if not self._rps:
            await self.discover_all()

        rp = self._rps.get(issuer)
        if rp is None:
            raise ValueError(f"Token issuer '{issuer}' is not a known upstream provider")

        # Find the matching provider config for claims mapping
        matching_provider = (
            p.claims_mapping for p in self._providers if p.config.issuer_url.rstrip("/") == issuer
        )
        mapping = next(matching_provider, ClaimsMapping())

        claims = await rp.validate_token(raw_token, expected_nonce)
        return _apply_claims_mapping(claims, mapping, unverified)

    @property
    def provider_names(self) -> list[str]:
        """Return names of all configured providers."""
        return [p.name for p in self._providers]


def _apply_claims_mapping(
    claims: Claims, mapping: ClaimsMapping, raw_payload: dict[str, Any]
) -> Claims:
    """Re-map claims from external provider format to internal Claims format."""
    # Apply custom field mappings from raw_payload if configured differently
    tenant = raw_payload.get(mapping.tenant_claim) or claims.tenant
    roles_raw = raw_payload.get(mapping.roles_claim) or claims.roles
    teams_raw = raw_payload.get(mapping.teams_claim) or claims.teams

    # Normalize roles and teams to lists
    roles = roles_raw if isinstance(roles_raw, list) else ([roles_raw] if roles_raw else [])
    teams = teams_raw if isinstance(teams_raw, list) else ([teams_raw] if teams_raw else [])

    ext = dict(claims.ext) if mapping.ext_passthrough else {}
    if mapping.ext_passthrough:
        # Include any unmapped claims in ext
        standard_keys = {
            "sub",
            "iss",
            "aud",
            "iat",
            "exp",
            "scope",
            "roles",
            "teams",
            "tenant",
            "nonce",
            "jti",
        }
        for k, v in raw_payload.items():
            if k not in standard_keys:
                ext[k] = v

    return Claims(
        sub=claims.sub,
        iss=claims.iss,
        aud=claims.aud,
        iat=claims.iat,
        exp=claims.exp,
        scope=claims.scope,
        roles=roles,
        tenant=tenant or "",
        teams=teams,
        ext=ext,
    )
