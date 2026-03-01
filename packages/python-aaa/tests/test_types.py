"""Tests for penguin_aaa.authn.types."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from penguin_aaa.authn.types import (
    ALLOWED_PROVIDER_ALGORITHMS,
    ALLOWED_RP_ALGORITHMS,
    MAX_SUBJECT_LENGTH,
    MAX_TOKEN_SIZE,
    Claims,
    TokenSet,
)


def _make_claims(**overrides):
    """Return a valid Claims dict, optionally overriding fields."""
    now = datetime.now(UTC)
    base = {
        "sub": "user-123",
        "iss": "https://idp.example.com",
        "aud": ["api.example.com"],
        "iat": now,
        "exp": now,
        "scope": ["openid", "profile"],
        "tenant": "acme",
    }
    base.update(overrides)
    return base


class TestConstants:
    def test_max_subject_length(self):
        assert MAX_SUBJECT_LENGTH == 256

    def test_max_token_size(self):
        assert MAX_TOKEN_SIZE == 8192

    def test_allowed_rp_algorithms_excludes_hmac(self):
        assert "HS256" not in ALLOWED_RP_ALGORITHMS
        assert "none" not in ALLOWED_RP_ALGORITHMS

    def test_allowed_provider_algorithms_excludes_hmac(self):
        assert "HS256" not in ALLOWED_PROVIDER_ALGORITHMS
        assert "none" not in ALLOWED_PROVIDER_ALGORITHMS

    def test_allowed_rp_algorithms_contains_rs256(self):
        assert "RS256" in ALLOWED_RP_ALGORITHMS

    def test_allowed_provider_algorithms_contains_es256(self):
        assert "ES256" in ALLOWED_PROVIDER_ALGORITHMS


class TestClaims:
    def test_valid_claims(self):
        data = _make_claims()
        claims = Claims.model_validate(data)
        assert claims.sub == "user-123"
        assert claims.tenant == "acme"
        assert claims.roles == []
        assert claims.teams == []
        assert claims.ext == {}

    def test_sub_max_length_enforced(self):
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(sub="x" * (MAX_SUBJECT_LENGTH + 1)))

    def test_sub_exactly_max_length_is_valid(self):
        claims = Claims.model_validate(_make_claims(sub="x" * MAX_SUBJECT_LENGTH))
        assert len(claims.sub) == MAX_SUBJECT_LENGTH

    def test_empty_sub_rejected(self):
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(sub=""))

    def test_whitespace_sub_rejected(self):
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(sub="   "))

    def test_empty_tenant_rejected(self):
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(tenant=""))

    def test_whitespace_tenant_rejected(self):
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(tenant="  "))

    def test_roles_defaults_to_empty_list(self):
        claims = Claims.model_validate(_make_claims())
        assert claims.roles == []

    def test_explicit_roles_stored(self):
        claims = Claims.model_validate(_make_claims(roles=["admin", "viewer"]))
        assert claims.roles == ["admin", "viewer"]

    def test_ext_defaults_to_empty_dict(self):
        claims = Claims.model_validate(_make_claims())
        assert claims.ext == {}

    def test_strict_mode_rejects_extra_coercion(self):
        # In strict mode, int cannot be passed where str is expected
        with pytest.raises(ValidationError):
            Claims.model_validate(_make_claims(sub=12345))


class TestTokenSet:
    def test_valid_token_set(self):
        ts = TokenSet.model_validate(
            {
                "access_token": "acc",
                "id_token": "idt",
                "refresh_token": "ref",
                "expires_in": 3600,
            }
        )
        assert ts.token_type == "Bearer"
        assert ts.expires_in == 3600

    def test_custom_token_type(self):
        ts = TokenSet.model_validate(
            {
                "access_token": "acc",
                "id_token": "idt",
                "refresh_token": "ref",
                "expires_in": 900,
                "token_type": "DPoP",
            }
        )
        assert ts.token_type == "DPoP"

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            TokenSet.model_validate(
                {
                    "access_token": "acc",
                    "id_token": "idt",
                    # refresh_token missing
                    "expires_in": 3600,
                }
            )
