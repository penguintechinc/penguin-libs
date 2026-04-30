"""Tests for Flask OIDC endpoints blueprint."""

from datetime import UTC, datetime, timedelta

import pytest

from penguin_aaa.authn.oidc_provider import OIDCProvider, OIDCProviderConfig
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, OIDCRPConfig
from penguin_aaa.authn.types import Claims
from penguin_aaa.crypto.keystore import MemoryKeyStore
from penguin_aaa.endpoints.flask_bp import create_oidc_blueprint
from penguin_aaa.token_store.memory import MemoryTokenStore


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


@pytest.fixture
def flask_app():
    """Create a Flask app with OIDC blueprint."""
    try:
        from flask import Flask
    except ImportError:
        pytest.skip("Flask not installed")

    app = Flask(__name__)

    provider_config = OIDCProviderConfig(
        issuer="https://auth.example.com",
        audiences=["client-123"],
    )
    provider_keystore = MemoryKeyStore()
    token_store = MemoryTokenStore()
    provider = OIDCProvider(provider_config, provider_keystore, token_store)

    rp_config = OIDCRPConfig(
        issuer_url="https://auth.example.com",
        client_id="client-123",
        client_secret="secret-xyz",
        redirect_url="https://app.example.com/callback",
    )
    rp = OIDCRelyingParty(rp_config)

    bp = create_oidc_blueprint(provider, rp)
    app.register_blueprint(bp)

    return app, provider, rp, token_store


class TestDiscoveryEndpoint:
    def test_discovery_document(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.get("/.well-known/openid-configuration")

        assert response.status_code == 200
        data = response.get_json()
        assert data["issuer"] == "https://auth.example.com"
        assert "token_endpoint" in data
        assert "jwks_uri" in data


class TestJWKSEndpoint:
    def test_jwks_endpoint(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.get("/.well-known/jwks.json")

        assert response.status_code == 200
        data = response.get_json()
        assert "keys" in data
        assert response.cache_control.max_age == 3600


class TestTokenEndpoint:
    def test_refresh_token_grant(self, flask_app):
        app, provider, _, _ = flask_app
        client = app.test_client()

        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        response = client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_set.refresh_token,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["expires_in"]

    def test_token_endpoint_missing_refresh_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post(
            "/oauth2/token",
            data={"grant_type": "refresh_token"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_token_endpoint_invalid_refresh_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": "invalid-token",
            },
        )

        assert response.status_code == 400

    def test_token_endpoint_auth_code_grant_not_implemented(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post(
            "/oauth2/token",
            data={"grant_type": "authorization_code", "code": "auth-code-123"},
        )

        assert response.status_code == 501

    def test_token_endpoint_unsupported_grant_type(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials"},
        )

        assert response.status_code == 400


class TestRevokeEndpoint:
    def test_revoke_refresh_token(self, flask_app):
        app, provider, _, _ = flask_app
        client = app.test_client()

        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        response = client.post(
            "/oauth2/revoke",
            data={
                "token": token_set.refresh_token,
                "token_type_hint": "refresh_token",
            },
        )

        assert response.status_code == 200

    def test_revoke_missing_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post("/oauth2/revoke", data={})

        assert response.status_code == 400

    def test_revoke_invalid_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        # RFC 7009: always return 200, even for invalid tokens
        response = client.post(
            "/oauth2/revoke",
            data={"token": "invalid-token"},
        )

        assert response.status_code == 200


class TestIntrospectEndpoint:
    def test_introspect_valid_token(self, flask_app):
        app, provider, _, _ = flask_app
        client = app.test_client()

        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        response = client.post(
            "/oauth2/introspect",
            data={"token": token_set.access_token},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["active"] is True
        assert data["sub"] == claims.sub

    def test_introspect_invalid_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post(
            "/oauth2/introspect",
            data={"token": "invalid-token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["active"] is False

    def test_introspect_missing_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.post("/oauth2/introspect", data={})

        assert response.status_code == 200
        data = response.get_json()
        assert data["active"] is False


class TestUserinfoEndpoint:
    @pytest.mark.asyncio
    async def test_userinfo_valid_token(self, flask_app):
        app, provider, _, _ = flask_app
        client = app.test_client()

        claims = _make_claims()
        token_set = provider.issue_token_set(claims)

        response = client.get(
            "/oauth2/userinfo",
            headers={"Authorization": f"Bearer {token_set.access_token}"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["sub"] == claims.sub
        assert data["tenant"] == claims.tenant

    def test_userinfo_missing_authorization(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.get("/oauth2/userinfo")

        assert response.status_code == 401

    def test_userinfo_invalid_token(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.get(
            "/oauth2/userinfo",
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401

    def test_userinfo_malformed_authorization_header(self, flask_app):
        app, _, _, _ = flask_app
        client = app.test_client()

        response = client.get(
            "/oauth2/userinfo",
            headers={"Authorization": "Basic xyz"},
        )

        assert response.status_code == 401
