"""Tests for penguin_aaa.authn.oidc_provider."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from penguin_aaa.authn.oidc_provider import OIDCProvider, OIDCProviderConfig
from penguin_aaa.authn.types import Claims
from penguin_aaa.crypto.keystore import MemoryKeyStore


def _make_claims() -> Claims:
    now = datetime.now(timezone.utc)
    return Claims.model_validate(
        {
            "sub": "user-abc",
            "iss": "https://auth.example.com",
            "aud": ["api.example.com"],
            "iat": now,
            "exp": now + timedelta(hours=1),
            "scope": ["openid", "profile"],
            "roles": ["admin"],
            "tenant": "acme",
            "teams": ["eng"],
        }
    )


def _make_provider(
    algorithm: str = "RS256",
    token_ttl: timedelta = timedelta(hours=1),
) -> tuple[OIDCProvider, MemoryKeyStore]:
    config = OIDCProviderConfig(
        issuer="https://auth.example.com",
        audiences=["api.example.com"],
        algorithm=algorithm,
        token_ttl=token_ttl,
    )
    keystore = MemoryKeyStore(algorithm=algorithm)
    return OIDCProvider(config, keystore), keystore


class TestOIDCProviderConfig:
    def test_valid_config(self):
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        assert config.algorithm == "RS256"
        assert config.token_ttl == timedelta(hours=1)
        assert config.refresh_ttl == timedelta(hours=24)

    def test_http_issuer_rejected_for_non_localhost(self):
        with pytest.raises(ValueError, match="HTTPS"):
            OIDCProviderConfig(
                issuer="http://auth.example.com",
                audiences=["api.example.com"],
            )

    def test_localhost_http_issuer_allowed(self):
        config = OIDCProviderConfig(
            issuer="http://localhost:8080",
            audiences=["api.example.com"],
        )
        assert config.issuer == "http://localhost:8080"

    def test_empty_audiences_rejected(self):
        with pytest.raises(ValueError, match="audiences"):
            OIDCProviderConfig(
                issuer="https://auth.example.com",
                audiences=[],
            )

    def test_hs256_algorithm_rejected(self):
        with pytest.raises(ValueError, match="explicitly forbidden"):
            OIDCProviderConfig(
                issuer="https://auth.example.com",
                audiences=["api"],
                algorithm="HS256",
            )

    def test_none_algorithm_rejected(self):
        with pytest.raises(ValueError, match="explicitly forbidden"):
            OIDCProviderConfig(
                issuer="https://auth.example.com",
                audiences=["api"],
                algorithm="none",
            )


class TestOIDCProviderIssueTokenSet:
    def test_returns_token_set(self):
        provider, _ = _make_provider()
        token_set = provider.issue_token_set(_make_claims())
        assert token_set.access_token
        assert token_set.id_token
        assert token_set.refresh_token
        assert token_set.token_type == "Bearer"
        assert token_set.expires_in == 3600

    def test_access_token_is_valid_jwt(self):
        provider, keystore = _make_provider()
        token_set = provider.issue_token_set(_make_claims())

        # Decode without verification to inspect structure
        header = jwt.get_unverified_header(token_set.access_token)
        assert header["alg"] == "RS256"
        assert "kid" in header

    def test_access_token_contains_expected_claims(self):
        provider, keystore = _make_provider()
        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        signing_key, kid = keystore.get_signing_key()
        public_key = signing_key.public_key()

        payload = jwt.decode(
            token_set.access_token,
            public_key,
            algorithms=["RS256"],
            audience=["api.example.com"],
        )
        assert payload["sub"] == "user-abc"
        assert payload["tenant"] == "acme"
        assert "admin" in payload["roles"]

    def test_id_token_contains_expected_claims(self):
        provider, keystore = _make_provider()
        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        signing_key, _ = keystore.get_signing_key()
        public_key = signing_key.public_key()

        payload = jwt.decode(
            token_set.id_token,
            public_key,
            algorithms=["RS256"],
            audience=["api.example.com"],
        )
        assert payload["sub"] == "user-abc"
        assert payload["token_use"] == "id"

    def test_refresh_token_is_opaque_string(self):
        provider, _ = _make_provider()
        token_set = provider.issue_token_set(_make_claims())
        # Opaque: not a valid JWT
        parts = token_set.refresh_token.split(".")
        assert len(parts) != 3

    def test_expires_in_reflects_token_ttl(self):
        provider, _ = _make_provider(token_ttl=timedelta(minutes=15))
        token_set = provider.issue_token_set(_make_claims())
        assert token_set.expires_in == 900

    def test_ec_algorithm_produces_valid_token(self):
        provider, keystore = _make_provider(algorithm="ES256")
        token_set = provider.issue_token_set(_make_claims())

        signing_key, _ = keystore.get_signing_key()
        public_key = signing_key.public_key()

        payload = jwt.decode(
            token_set.access_token,
            public_key,
            algorithms=["ES256"],
            audience=["api.example.com"],
        )
        assert payload["sub"] == "user-abc"


class TestOIDCProviderDiscoveryDocument:
    def test_discovery_document_structure(self):
        provider, _ = _make_provider()
        doc = provider.discovery_document()

        required_keys = {
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "response_types_supported",
            "id_token_signing_alg_values_supported",
        }
        assert required_keys.issubset(set(doc.keys()))

    def test_discovery_document_issuer(self):
        provider, _ = _make_provider()
        doc = provider.discovery_document()
        assert doc["issuer"] == "https://auth.example.com"

    def test_discovery_document_jwks_uri(self):
        provider, _ = _make_provider()
        doc = provider.discovery_document()
        assert doc["jwks_uri"] == "https://auth.example.com/.well-known/jwks.json"

    def test_discovery_document_algorithm(self):
        provider, _ = _make_provider(algorithm="ES256")
        doc = provider.discovery_document()
        assert "ES256" in doc["id_token_signing_alg_values_supported"]


class TestOIDCProviderJwks:
    def test_jwks_returns_public_keys(self):
        provider, _ = _make_provider()
        jwks = provider.jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) >= 1
        assert jwks["keys"][0]["kty"] == "RSA"
