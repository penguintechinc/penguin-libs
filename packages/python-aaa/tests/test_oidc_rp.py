"""Tests for penguin_aaa.authn.oidc_rp."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest

from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, OIDCRPConfig, _normalise_list_fields
from penguin_aaa.crypto.keystore import MemoryKeyStore

ISSUER = "https://idp.example.com"
CLIENT_ID = "my-client"


def _make_rp_config(**overrides) -> OIDCRPConfig:
    base = {
        "issuer_url": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": "secret",
        "redirect_url": "https://app.example.com/callback",
    }
    base.update(overrides)
    return OIDCRPConfig(**base)


def _make_discovery_doc(keystore: MemoryKeyStore) -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth2/authorize",
        "token_endpoint": f"{ISSUER}/oauth2/token",
        "userinfo_endpoint": f"{ISSUER}/oauth2/userinfo",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
    }


def _issue_test_token(
    keystore: MemoryKeyStore,
    algorithm: str = "RS256",
    audience: str = CLIENT_ID,
    sub: str = "user-123",
    tenant: str = "acme",
    extra_claims: dict | None = None,
) -> str:
    signing_key, kid = keystore.get_signing_key()
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "iss": ISSUER,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "scope": "openid profile",
        "tenant": tenant,
        "roles": [],
        "teams": [],
        "ext": {},
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, signing_key, algorithm=algorithm, headers={"kid": kid})


class TestOIDCRPConfig:
    def test_valid_config(self):
        config = _make_rp_config()
        assert config.issuer_url == ISSUER
        assert config.algorithms == ["RS256"]

    def test_http_issuer_rejected_for_non_localhost(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _make_rp_config(issuer_url="http://idp.example.com")

    def test_localhost_http_issuer_allowed(self):
        config = _make_rp_config(issuer_url="http://localhost:8080")
        assert config.issuer_url == "http://localhost:8080"

    def test_http_redirect_rejected_for_non_localhost(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _make_rp_config(redirect_url="http://app.example.com/cb")

    def test_disallowed_algorithm_rejected(self):
        with pytest.raises(ValueError, match="not allowed"):
            _make_rp_config(algorithms=["HS256"])


class TestOIDCRelyingPartyDiscover:
    @pytest.mark.asyncio
    async def test_discover_fetches_and_caches_document(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        keystore = MemoryKeyStore()

        discovery_doc = _make_discovery_doc(keystore)

        mock_response = MagicMock()
        mock_response.json.return_value = discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            doc1 = await rp.discover()
            doc2 = await rp.discover()

        assert doc1["issuer"] == ISSUER
        assert doc1 is doc2  # cache hit

    @pytest.mark.asyncio
    async def test_discover_raises_on_missing_required_fields(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"issuer": ISSUER}  # missing fields
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            with pytest.raises(ValueError, match="missing required fields"):
                await rp.discover()


class TestOIDCRelyingPartyValidateToken:
    @pytest.mark.asyncio
    async def test_validate_token_returns_claims(self):
        keystore = MemoryKeyStore(algorithm="RS256")
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)

        token = _issue_test_token(keystore)

        # Pre-populate _jwks_client with a mock that returns the real signing key
        signing_key, kid = keystore.get_signing_key()
        public_key = signing_key.public_key()

        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        rp._discovery = _make_discovery_doc(keystore)
        rp._jwks_client = mock_jwks_client

        claims = await rp.validate_token(token)
        assert claims.sub == "user-123"
        assert claims.tenant == "acme"

    @pytest.mark.asyncio
    async def test_oversized_token_rejected(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        rp._discovery = {"issuer": ISSUER}
        rp._jwks_client = MagicMock()

        oversized = "x" * 8193
        with pytest.raises(ValueError, match="exceeds maximum"):
            await rp.validate_token(oversized)


class TestOIDCRelyingPartyStateHelpers:
    def test_generate_state_is_urlsafe_string(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        state = rp.generate_state()
        assert len(state) > 20
        assert all(c.isalnum() or c in "-_" for c in state)

    def test_validate_state_matches(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        state = rp.generate_state()
        assert rp.validate_state(state, state) is True

    def test_validate_state_mismatches(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        assert rp.validate_state("abc", "xyz") is False


class TestOIDCRelyingPartyBuildAuthorizationUrl:
    def test_raises_if_not_discovered(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        with pytest.raises(RuntimeError, match="discover"):
            rp.build_authorization_url("state-value")

    def test_url_contains_required_params(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        rp._discovery = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/oauth2/authorize",
            "token_endpoint": f"{ISSUER}/oauth2/token",
            "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        }

        url = rp.build_authorization_url("my-state")
        assert "response_type=code" in url
        assert f"client_id={CLIENT_ID}" in url
        assert "state=my-state" in url
        assert "redirect_uri=" in url

    def test_url_includes_nonce_when_provided(self):
        config = _make_rp_config()
        rp = OIDCRelyingParty(config)
        rp._discovery = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/oauth2/authorize",
            "token_endpoint": f"{ISSUER}/oauth2/token",
            "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        }

        url = rp.build_authorization_url("my-state", nonce="my-nonce")
        assert "nonce=my-nonce" in url


class TestNormaliseListFields:
    def test_space_separated_scope_is_split(self):
        payload = {"scope": "openid profile email"}
        _normalise_list_fields(payload, ("scope",))
        assert payload["scope"] == ["openid", "profile", "email"]

    def test_none_value_becomes_empty_list(self):
        payload: dict = {}
        _normalise_list_fields(payload, ("roles",))
        assert payload["roles"] == []

    def test_existing_list_is_unchanged(self):
        payload = {"roles": ["admin", "viewer"]}
        _normalise_list_fields(payload, ("roles",))
        assert payload["roles"] == ["admin", "viewer"]

    def test_bare_string_non_scope_wrapped_in_list(self):
        payload = {"aud": "api.example.com"}
        _normalise_list_fields(payload, ("aud",))
        assert payload["aud"] == ["api.example.com"]
