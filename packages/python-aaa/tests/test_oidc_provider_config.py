"""Tests for OIDCProviderConfig short-window JWT defaults."""

from datetime import timedelta

import pytest

from penguin_aaa.authn.oidc_provider import OIDCProviderConfig


class TestOIDCProviderConfigTokenTTL:
    def test_default_token_ttl_is_15_minutes(self) -> None:
        """Test that token_ttl defaults to 15 minutes."""
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        assert config.token_ttl == timedelta(minutes=15)

    def test_default_max_token_ttl_is_1_hour(self) -> None:
        """Test that max_token_ttl defaults to 1 hour."""
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        assert config.max_token_ttl == timedelta(hours=1)

    def test_token_ttl_less_than_max_passes(self) -> None:
        """Test that token_ttl <= max_token_ttl passes validation."""
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
            token_ttl=timedelta(minutes=30),
            max_token_ttl=timedelta(hours=1),
        )
        assert config.token_ttl == timedelta(minutes=30)
        assert config.max_token_ttl == timedelta(hours=1)

    def test_token_ttl_equal_to_max_passes(self) -> None:
        """Test that token_ttl == max_token_ttl passes validation."""
        ttl = timedelta(hours=1)
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
            token_ttl=ttl,
            max_token_ttl=ttl,
        )
        assert config.token_ttl == ttl

    def test_token_ttl_exceeds_max_raises_error(self) -> None:
        """Test that token_ttl > max_token_ttl raises ValueError."""
        with pytest.raises(ValueError, match="token_ttl .* exceeds max_token_ttl"):
            OIDCProviderConfig(
                issuer="https://auth.example.com",
                audiences=["api.example.com"],
                token_ttl=timedelta(hours=2),
                max_token_ttl=timedelta(hours=1),
            )

    def test_custom_token_ttl_still_valid(self) -> None:
        """Test that custom token_ttl within max can be set."""
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
            token_ttl=timedelta(minutes=45),
        )
        assert config.token_ttl == timedelta(minutes=45)
        assert config.max_token_ttl == timedelta(hours=1)

    def test_refresh_ttl_unchanged(self) -> None:
        """Test that refresh_ttl defaults to 24 hours (unchanged)."""
        config = OIDCProviderConfig(
            issuer="https://auth.example.com",
            audiences=["api.example.com"],
        )
        assert config.refresh_ttl == timedelta(hours=24)
