"""Tests for OIDC Provider lifecycle methods (refresh, revoke, introspect)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from penguin_aaa.authn.oidc_provider import OIDCProvider, OIDCProviderConfig
from penguin_aaa.authn.types import Claims
from penguin_aaa.crypto.keystore import MemoryKeyStore
from penguin_aaa.token_store.memory import MemoryTokenStore


def _make_claims() -> Claims:
    now = datetime.now(UTC)
    return Claims.model_validate({
        "sub": "user-abc",
        "iss": "https://auth.example.com",
        "aud": ["api.example.com"],
        "iat": now,
        "exp": now + timedelta(hours=1),
        "scope": ["openid", "profile"],
        "roles": ["admin"],
        "tenant": "acme",
        "teams": ["eng"],
    })


def _make_provider_with_store() -> tuple[OIDCProvider, MemoryKeyStore, MemoryTokenStore]:
    config = OIDCProviderConfig(
        issuer="https://auth.example.com",
        audiences=["api.example.com"],
        algorithm="RS256",
        token_ttl=timedelta(hours=1),
        refresh_ttl=timedelta(hours=24),
    )
    keystore = MemoryKeyStore(algorithm="RS256")
    token_store = MemoryTokenStore()
    provider = OIDCProvider(config, keystore, token_store)
    return provider, keystore, token_store


class TestOIDCProviderRefresh:
    def test_refresh_valid_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        # Issue initial token set
        token_set_1 = provider.issue_token_set(claims)
        assert token_set_1.refresh_token

        # Refresh with the refresh token
        token_set_2 = provider.refresh(token_set_1.refresh_token)
        assert token_set_2.access_token != token_set_1.access_token
        assert token_set_2.refresh_token != token_set_1.refresh_token

    def test_refresh_invalid_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        with pytest.raises(ValueError, match="Invalid or expired refresh token"):
            provider.refresh("invalid-refresh-token")

    def test_refresh_revoked_token(self) -> None:
        provider, _, token_store = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        token_store.revoke_refresh(token_set.refresh_token)

        with pytest.raises(ValueError, match="Invalid or expired refresh token"):
            provider.refresh(token_set.refresh_token)

    def test_refresh_without_token_store(self) -> None:
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        provider = OIDCProvider(config, MemoryKeyStore(), None)
        with pytest.raises(ValueError, match="token_store not configured"):
            provider.refresh("any-token")


class TestOIDCProviderRevoke:
    def test_revoke_refresh_token(self) -> None:
        provider, _, token_store = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        provider.revoke(token_set.refresh_token, "refresh_token")

        # Token should be revoked
        with pytest.raises(ValueError):
            provider.refresh(token_set.refresh_token)

    def test_revoke_access_token(self) -> None:
        provider, _, token_store = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        provider.revoke(token_set.access_token)

        # Check JTI is revoked
        payload = jwt.decode(token_set.access_token, options={"verify_signature": False})
        jti = payload.get("jti")
        assert token_store.is_jti_revoked(jti) is True

    def test_revoke_nonexistent_token_succeeds(self) -> None:
        provider, _, _ = _make_provider_with_store()
        # Should not raise
        provider.revoke("nonexistent-token")
        provider.revoke("nonexistent", "refresh_token")

    def test_revoke_invalid_jwt_succeeds(self) -> None:
        provider, _, _ = _make_provider_with_store()
        # Should not raise (silently ignore invalid JWTs)
        provider.revoke("not.a.jwt")

    def test_revoke_without_token_store(self) -> None:
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        provider = OIDCProvider(config, MemoryKeyStore(), None)
        # Should not raise (no-op)
        provider.revoke("any-token")


class TestOIDCProviderIntrospect:
    def test_introspect_valid_access_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        result = provider.introspect(token_set.access_token)

        assert result["active"] is True
        assert result["sub"] == claims.sub
        assert result["tenant"] == claims.tenant

    def test_introspect_revoked_access_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        provider.revoke(token_set.access_token)

        result = provider.introspect(token_set.access_token)
        assert result["active"] is False

    def test_introspect_valid_refresh_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        result = provider.introspect(token_set.refresh_token)

        assert result["active"] is True
        assert result["sub"] == claims.sub

    def test_introspect_revoked_refresh_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        provider.revoke(token_set.refresh_token, "refresh_token")

        result = provider.introspect(token_set.refresh_token)
        assert result["active"] is False

    def test_introspect_invalid_token(self) -> None:
        provider, _, _ = _make_provider_with_store()
        result = provider.introspect("invalid-token")
        assert result["active"] is False

    def test_introspect_without_token_store(self) -> None:
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        provider = OIDCProvider(config, MemoryKeyStore(), None)
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)
        # Should be able to introspect JWT (without refresh token lookup)
        result = provider.introspect(token_set.access_token)
        assert result["active"] is True


class TestOIDCProviderNonce:
    def test_issue_token_with_nonce(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()
        nonce = "test-nonce-123"

        token_set = provider.issue_token_set(claims, nonce=nonce)

        # Verify nonce is in id_token
        id_payload = jwt.decode(token_set.id_token, options={"verify_signature": False})
        assert id_payload.get("nonce") == nonce

    def test_issue_token_without_nonce(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)

        # Verify nonce is not in id_token
        id_payload = jwt.decode(token_set.id_token, options={"verify_signature": False})
        assert "nonce" not in id_payload

    def test_jti_in_tokens(self) -> None:
        provider, _, _ = _make_provider_with_store()
        claims = _make_claims()

        token_set = provider.issue_token_set(claims)

        # Verify JTI is in both tokens
        access_payload = jwt.decode(token_set.access_token, options={"verify_signature": False})
        id_payload = jwt.decode(token_set.id_token, options={"verify_signature": False})

        assert "jti" in access_payload
        assert "jti" in id_payload
        assert access_payload["jti"] == id_payload["jti"]
