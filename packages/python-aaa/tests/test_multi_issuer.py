"""Tests for penguin_aaa.authn.multi_issuer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_aaa.authn.multi_issuer import (
    ClaimsMapping,
    MultiIssuerRelyingParty,
    UpstreamProvider,
)
from penguin_aaa.authn.oidc_rp import OIDCRPConfig
from penguin_aaa.authn.presets import okta_provider, skauswatch_provider
from penguin_aaa.authn.types import Claims


def _make_test_claims() -> Claims:
    now = datetime.now(UTC)
    return Claims.model_validate(
        {
            "sub": "user-123",
            "iss": "https://okta.example.com",
            "aud": ["api.example.com"],
            "iat": now,
            "exp": now + timedelta(hours=1),
            "scope": ["openid", "profile"],
            "roles": ["admin"],
            "tenant": "acme",
            "teams": ["eng"],
        }
    )


class TestClaimsMapping:
    def test_default_mapping(self) -> None:
        mapping = ClaimsMapping()
        assert mapping.sub_claim == "sub"
        assert mapping.iss_claim == "iss"
        assert mapping.tenant_claim == "tenant"
        assert mapping.roles_claim == "roles"
        assert mapping.teams_claim == "teams"
        assert mapping.ext_passthrough is True

    def test_custom_mapping(self) -> None:
        mapping = ClaimsMapping(
            tenant_claim="tid",
            roles_claim="groups",
        )
        assert mapping.tenant_claim == "tid"
        assert mapping.roles_claim == "groups"


class TestUpstreamProvider:
    def test_provider_creation(self) -> None:
        config = OIDCRPConfig(
            issuer_url="https://okta.example.com",
            client_id="client-id",
            client_secret="secret",
            redirect_url="https://app.example.com/callback",
        )
        provider = UpstreamProvider(
            name="okta",
            config=config,
        )
        assert provider.name == "okta"
        assert provider.config.issuer_url == "https://okta.example.com"
        assert provider.claims_mapping.roles_claim == "roles"


class TestMultiIssuerRelyingParty:
    def test_empty_providers_rejected(self) -> None:
        with pytest.raises(ValueError, match="At least one upstream provider"):
            MultiIssuerRelyingParty([])

    def test_provider_names_property(self) -> None:
        okta_cfg = OIDCRPConfig(
            issuer_url="https://okta.example.com",
            client_id="okta-id",
            client_secret="okta-secret",
            redirect_url="https://app.example.com/callback",
        )
        skauswatch_cfg = OIDCRPConfig(
            issuer_url="https://skauswatch.example.com",
            client_id="skauswatch-id",
            client_secret="skauswatch-secret",
            redirect_url="https://app.example.com/callback",
        )
        providers = [
            UpstreamProvider("okta", okta_cfg),
            UpstreamProvider("skauswatch", skauswatch_cfg),
        ]
        rp = MultiIssuerRelyingParty(providers)
        assert rp.provider_names == ["okta", "skauswatch"]

    @pytest.mark.asyncio
    async def test_discover_all(self) -> None:
        config = OIDCRPConfig(
            issuer_url="https://okta.example.com",
            client_id="client-id",
            client_secret="secret",
            redirect_url="https://app.example.com/callback",
        )
        provider = UpstreamProvider("okta", config)
        rp = MultiIssuerRelyingParty([provider])

        # Mock the discovery response
        with patch("penguin_aaa.authn.oidc_rp.httpx.AsyncClient") as mock_client_class:
            # Use MagicMock for response since json() is not async
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "issuer": "https://okta.example.com",
                "jwks_uri": "https://okta.example.com/.well-known/jwks.json",
                "authorization_endpoint": "https://okta.example.com/oauth2/authorize",
                "token_endpoint": "https://okta.example.com/oauth2/token",
            }
            mock_response.raise_for_status.return_value = None
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await rp.discover_all()
            assert len(rp._rps) == 1
            assert "https://okta.example.com" in rp._rps

    @pytest.mark.asyncio
    async def test_validate_token_unknown_issuer(self) -> None:
        config = OIDCRPConfig(
            issuer_url="https://okta.example.com",
            client_id="client-id",
            client_secret="secret",
            redirect_url="https://app.example.com/callback",
        )
        provider = UpstreamProvider("okta", config)
        rp = MultiIssuerRelyingParty([provider])

        # Pre-populate RPs to skip discovery
        from penguin_aaa.authn.oidc_rp import OIDCRelyingParty
        rp._rps["https://okta.example.com"] = OIDCRelyingParty(config)

        # Token with unknown issuer
        import jwt
        unknown_token = jwt.encode(
            {"iss": "https://unknown.example.com", "sub": "user"},
            "secret",
            algorithm="HS256",
        )

        with pytest.raises(ValueError, match="not a known upstream provider"):
            await rp.validate_token(unknown_token)

    @pytest.mark.asyncio
    async def test_validate_token_invalid_token(self) -> None:
        config = OIDCRPConfig(
            issuer_url="https://okta.example.com",
            client_id="client-id",
            client_secret="secret",
            redirect_url="https://app.example.com/callback",
        )
        provider = UpstreamProvider("okta", config)
        rp = MultiIssuerRelyingParty([provider])

        with pytest.raises(ValueError, match="Cannot decode token header"):
            await rp.validate_token("not-a-jwt")


class TestPresetsOkta:
    def test_okta_preset_configuration(self) -> None:
        provider = okta_provider(
            issuer_url="https://tenant.okta.com",
            client_id="0oa123",
            client_secret="secret",
            redirect_url="https://app.example.com/callback",
        )
        assert provider.name == "okta"
        assert provider.config.issuer_url == "https://tenant.okta.com"
        assert provider.config.client_id == "0oa123"
        assert "groups" in provider.config.scopes
        assert provider.claims_mapping.roles_claim == "groups"
        assert provider.claims_mapping.tenant_claim == "tid"


class TestPresetsSkausWatch:
    def test_skauswatch_preset_configuration(self) -> None:
        provider = skauswatch_provider(
            issuer_url="https://auth.skauswatch.example.com",
            client_id="skw-client",
            client_secret="skw-secret",
            redirect_url="https://app.example.com/callback",
        )
        assert provider.name == "skauswatch"
        assert provider.config.issuer_url == "https://auth.skauswatch.example.com"
        assert provider.config.client_id == "skw-client"
        assert provider.claims_mapping.roles_claim == "roles"
        assert provider.claims_mapping.tenant_claim == "tenant"


class TestClaimsMappingApplication:
    def test_okta_claims_mapping(self) -> None:
        """Test that Okta claims (groups, tid) are mapped to internal claims (roles, tenant)."""
        from penguin_aaa.authn.multi_issuer import _apply_claims_mapping

        claims = _make_test_claims()
        mapping = ClaimsMapping(
            roles_claim="groups",
            tenant_claim="tid",
        )
        raw_payload = {
            "sub": "user-123",
            "iss": "https://okta.example.com",
            "aud": ["api.example.com"],
            "iat": int(claims.iat.timestamp()),
            "exp": int(claims.exp.timestamp()),
            "scope": ["openid", "profile"],
            "groups": ["admin", "engineering"],
            "tid": "org-123",
            "teams": ["backend"],
            "custom_claim": "custom_value",
        }

        mapped = _apply_claims_mapping(claims, mapping, raw_payload)
        assert mapped.roles == ["admin", "engineering"]
        assert mapped.tenant == "org-123"
        assert "custom_claim" in mapped.ext

    def test_skauswatch_claims_mapping(self) -> None:
        """Test that SkausWatch standard claims are preserved."""
        from penguin_aaa.authn.multi_issuer import _apply_claims_mapping

        claims = _make_test_claims()
        mapping = ClaimsMapping()  # Standard mapping
        raw_payload = {
            "sub": "user-123",
            "iss": "https://skauswatch.example.com",
            "aud": ["api.example.com"],
            "iat": int(claims.iat.timestamp()),
            "exp": int(claims.exp.timestamp()),
            "scope": ["openid", "profile"],
            "roles": ["user"],
            "tenant": "skauswatch-tenant",
            "teams": ["support"],
        }

        mapped = _apply_claims_mapping(claims, mapping, raw_payload)
        assert mapped.roles == ["user"]
        assert mapped.tenant == "skauswatch-tenant"
        assert mapped.teams == ["support"]

    def test_non_list_roles_converted_to_list(self) -> None:
        """Test that scalar role values are converted to lists."""
        from penguin_aaa.authn.multi_issuer import _apply_claims_mapping

        claims = _make_test_claims()
        mapping = ClaimsMapping()
        raw_payload = {
            "sub": "user-123",
            "iss": "https://skauswatch.example.com",
            "aud": ["api.example.com"],
            "iat": int(claims.iat.timestamp()),
            "exp": int(claims.exp.timestamp()),
            "scope": ["openid"],
            "roles": "single_role",  # Scalar, not list
            "tenant": "acme",
            "teams": "team-a",  # Scalar, not list
        }

        mapped = _apply_claims_mapping(claims, mapping, raw_payload)
        assert mapped.roles == ["single_role"]
        assert mapped.teams == ["team-a"]
