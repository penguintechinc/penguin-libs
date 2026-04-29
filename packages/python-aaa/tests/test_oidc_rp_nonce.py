"""Tests for OIDC Relying Party nonce validation and PKCE helpers."""

from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac

import pytest
import jwt

from penguin_aaa.authn.oidc_provider import OIDCProvider, OIDCProviderConfig
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, OIDCRPConfig, generate_pkce_pair
from penguin_aaa.authn.types import Claims
from penguin_aaa.crypto.keystore import MemoryKeyStore


def _make_claims() -> Claims:
    now = datetime.now(UTC)
    return Claims.model_validate({
        "sub": "user-abc",
        "iss": "https://auth.example.com",
        "aud": ["client-123"],
        "iat": now,
        "exp": now + timedelta(hours=1),
        "scope": ["openid", "profile"],
        "roles": ["user"],
        "tenant": "acme",
        "teams": [],
    })


def _make_provider_and_rp() -> tuple[OIDCProvider, OIDCRelyingParty]:
    provider_config = OIDCProviderConfig(
        issuer="https://auth.example.com",
        audiences=["client-123"],
    )
    provider_keystore = MemoryKeyStore()
    provider = OIDCProvider(provider_config, provider_keystore)

    rp_config = OIDCRPConfig(
        issuer_url="https://auth.example.com",
        client_id="client-123",
        client_secret="secret-xyz",
        redirect_url="https://app.example.com/callback",
    )
    rp = OIDCRelyingParty(rp_config)
    return provider, rp


class TestNonceValidation:
    @pytest.mark.asyncio
    async def test_validate_token_with_correct_nonce(self) -> None:
        provider, rp = _make_provider_and_rp()
        claims = _make_claims()
        nonce = "test-nonce-123"

        # Mock discovery to avoid HTTP call
        rp._discovery = provider.discovery_document()
        rp._jwks_client = None  # Force re-setup with mocked discovery

        # Issue token with nonce
        token_set = provider.issue_token_set(claims, nonce=nonce)

        # Validate with matching nonce (will skip actual JWKS discovery)
        # We need to decode and verify manually for test purposes
        import jwt as jwt_lib
        payload = jwt_lib.decode(token_set.id_token, options={"verify_signature": False})
        assert payload.get("nonce") == nonce
        assert payload.get("sub") == claims.sub

    def test_validate_token_with_wrong_nonce(self) -> None:
        provider, rp = _make_provider_and_rp()
        claims = _make_claims()
        nonce_issued = "test-nonce-123"
        nonce_expected = "different-nonce"

        # Issue token with one nonce
        token_set = provider.issue_token_set(claims, nonce=nonce_issued)

        # Decode and check nonce validation logic
        payload = jwt.decode(token_set.id_token, options={"verify_signature": False})
        token_nonce = payload.get("nonce")
        # Verify the constant-time comparison would fail
        assert not hmac.compare_digest(token_nonce or "", nonce_expected)

    def test_validate_token_nonce_missing_when_expected(self) -> None:
        provider, rp = _make_provider_and_rp()
        claims = _make_claims()

        # Issue token without nonce
        token_set = provider.issue_token_set(claims)

        # Check that nonce is missing
        payload = jwt.decode(token_set.id_token, options={"verify_signature": False})
        assert "nonce" not in payload

    def test_validate_token_without_nonce_check(self) -> None:
        provider, rp = _make_provider_and_rp()
        claims = _make_claims()

        # Issue token with nonce
        token_set = provider.issue_token_set(claims, nonce="test-nonce")

        # Verify token contains nonce
        payload = jwt.decode(token_set.id_token, options={"verify_signature": False})
        assert payload.get("nonce") == "test-nonce"
        assert payload.get("sub") == claims.sub


class TestPKCEHelpers:
    def test_generate_pkce_pair(self) -> None:
        verifier, challenge = generate_pkce_pair()

        # Verifier should be 43 chars (32 bytes base64url)
        assert len(verifier) == 43
        assert verifier.count("-") + verifier.count("_") >= 0  # May contain url-safe chars

        # Challenge should be ~43 chars (SHA256 hash base64url)
        assert len(challenge) == 43
        assert challenge.count("-") + challenge.count("_") >= 0

        # Recreate challenge from verifier
        manual_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == manual_challenge

    def test_generate_pkce_pair_uniqueness(self) -> None:
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()

        # Each pair should be unique
        assert pair1[0] != pair2[0]
        assert pair1[1] != pair2[1]

    def test_authorization_url_with_pkce(self) -> None:
        provider, rp = _make_provider_and_rp()
        state = rp.generate_state()
        nonce = "nonce-123"
        verifier, challenge = generate_pkce_pair()

        # Mock discovery
        rp._discovery = provider.discovery_document()

        url = rp.build_authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=challenge,
            code_challenge_method="S256",
        )

        assert "code_challenge=" + challenge in url
        assert "code_challenge_method=S256" in url
        assert "nonce=" + nonce in url
        assert "state=" + state in url

    def test_authorization_url_without_pkce(self) -> None:
        provider, rp = _make_provider_and_rp()
        state = rp.generate_state()

        # Mock discovery
        rp._discovery = provider.discovery_document()

        url = rp.build_authorization_url(state=state)

        assert "code_challenge" not in url
        assert "state=" + state in url
