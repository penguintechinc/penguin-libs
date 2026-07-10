"""Tests for static-key JWT verification (penguin_aaa.authn.static_key)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from penguin_aaa.authn.static_key import (
    StaticKeyConfig,
    StaticKeyVerifier,
    load_key_from_env_or_file,
)
from penguin_aaa.authn.types import Claims

ISSUER = "squawk-manager"
AUDIENCE = "squawk"


def _gen_es256_pem() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    return _gen_es256_pem()


def _payload(**overrides: object) -> dict:
    now = datetime.now(UTC)
    payload: dict = {
        "sub": "42",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "tenant": "default",
        "scope": "servers:read servers:write",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    payload.update(overrides)
    return payload


def _token(private_pem: str, algorithm: str = "ES256", **overrides: object) -> str:
    return jwt.encode(_payload(**overrides), private_pem, algorithm=algorithm)


def _verifier(public_pem: str, **config_overrides: object) -> StaticKeyVerifier:
    config = StaticKeyConfig(
        issuer=ISSUER, audience=AUDIENCE, public_key=public_pem, **config_overrides
    )
    return StaticKeyVerifier(config)


class TestValidTokens:
    def test_valid_es256_token_returns_claims(self, keypair):
        priv, pub = keypair
        claims = _verifier(pub).validate_token(_token(priv))
        assert isinstance(claims, Claims)
        assert claims.sub == "42"
        assert claims.tenant == "default"
        assert claims.scope == ["servers:read", "servers:write"]

    def test_verify_token_alias(self, keypair):
        priv, pub = keypair
        assert _verifier(pub).verify_token(_token(priv)).sub == "42"

    def test_verify_or_none_success(self, keypair):
        priv, pub = keypair
        assert _verifier(pub).verify_or_none(_token(priv)) is not None


class TestFailClosed:
    def test_wrong_key_rejected(self, keypair):
        _priv, pub = keypair
        attacker_priv, _ = _gen_es256_pem()
        with pytest.raises(jwt.InvalidSignatureError):
            _verifier(pub).validate_token(_token(attacker_priv))

    def test_hs256_rejected(self, keypair):
        """Algorithm confusion: HS256 never passes the asymmetric allowlist."""
        _priv, pub = keypair
        forged = jwt.encode(_payload(), "attacker-secret", algorithm="HS256")
        with pytest.raises(jwt.PyJWTError):
            _verifier(pub).validate_token(forged)

    def test_hs256_not_configurable(self):
        with pytest.raises(ValueError, match="not allowed"):
            StaticKeyConfig(issuer=ISSUER, audience=AUDIENCE, algorithms=["HS256"])

    def test_expired_rejected(self, keypair):
        priv, pub = keypair
        now = datetime.now(UTC)
        expired = _token(priv, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1))
        with pytest.raises(jwt.ExpiredSignatureError):
            _verifier(pub).validate_token(expired)

    def test_wrong_audience_rejected(self, keypair):
        priv, pub = keypair
        with pytest.raises(jwt.InvalidAudienceError):
            _verifier(pub).validate_token(_token(priv, aud="other-service"))

    def test_wrong_issuer_rejected(self, keypair):
        priv, pub = keypair
        with pytest.raises(jwt.InvalidIssuerError):
            _verifier(pub).validate_token(_token(priv, iss="evil-issuer"))

    def test_missing_tenant_rejected(self, keypair):
        priv, pub = keypair
        payload = _payload()
        del payload["tenant"]
        token = jwt.encode(payload, priv, algorithm="ES256")
        with pytest.raises(jwt.MissingRequiredClaimError):
            _verifier(pub).validate_token(token)

    def test_empty_tenant_rejected(self, keypair):
        priv, pub = keypair
        with pytest.raises(ValueError):
            _verifier(pub).validate_token(_token(priv, tenant="   "))

    def test_no_key_configured_raises(self, keypair, monkeypatch):
        priv, _pub = keypair
        monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("JWT_PUBLIC_KEY_FILE", raising=False)
        verifier = StaticKeyVerifier(StaticKeyConfig(issuer=ISSUER, audience=AUDIENCE))
        with pytest.raises(ValueError, match="No JWT public key configured"):
            verifier.validate_token(_token(priv))

    def test_oversized_token_rejected(self, keypair):
        _priv, pub = keypair
        with pytest.raises(ValueError, match="maximum allowed size"):
            _verifier(pub).validate_token("x" * 9000)

    def test_verify_or_none_returns_none_on_failure(self, keypair):
        _priv, pub = keypair
        attacker_priv, _ = _gen_es256_pem()
        assert _verifier(pub).verify_or_none(_token(attacker_priv)) is None
        assert _verifier(pub).verify_or_none("not-a-jwt") is None


class TestKeyLoading:
    def test_load_from_env(self, keypair, monkeypatch):
        _priv, pub = keypair
        monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
        assert load_key_from_env_or_file("JWT_PUBLIC_KEY", "JWT_PUBLIC_KEY_FILE") == pub

    def test_load_from_file(self, keypair, monkeypatch, tmp_path):
        _priv, pub = keypair
        key_file = tmp_path / "jwt-public-key.pem"
        key_file.write_text(pub + "\n")
        monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
        monkeypatch.setenv("JWT_PUBLIC_KEY_FILE", str(key_file))
        loaded = load_key_from_env_or_file("JWT_PUBLIC_KEY", "JWT_PUBLIC_KEY_FILE")
        assert loaded == pub.strip()

    def test_load_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("JWT_PUBLIC_KEY_FILE", raising=False)
        assert load_key_from_env_or_file("JWT_PUBLIC_KEY", "JWT_PUBLIC_KEY_FILE") is None

    def test_call_time_key_rotation(self, keypair, monkeypatch):
        """With no pinned key, the env key is read on every verification."""
        priv1, pub1 = keypair
        priv2, pub2 = _gen_es256_pem()

        verifier = StaticKeyVerifier(StaticKeyConfig(issuer=ISSUER, audience=AUDIENCE))

        monkeypatch.setenv("JWT_PUBLIC_KEY", pub1)
        assert verifier.verify_or_none(_token(priv1)) is not None
        assert verifier.verify_or_none(_token(priv2)) is None

        # Rotate: same verifier instance picks up the new key without restart.
        monkeypatch.setenv("JWT_PUBLIC_KEY", pub2)
        assert verifier.verify_or_none(_token(priv2)) is not None
        assert verifier.verify_or_none(_token(priv1)) is None
