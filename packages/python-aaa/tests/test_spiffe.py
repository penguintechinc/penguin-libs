"""Tests for penguin_aaa.authn.spiffe — SPIFFE identity validation."""

import pytest

from penguin_aaa.authn.spiffe import SPIFFEAuthenticator, SPIFFEConfig


class TestSPIFFEConfig:
    def test_valid_config(self):
        cfg = SPIFFEConfig(
            trust_domain="penguintech.io",
            workload_socket="/run/spire/agent.sock",
            allowed_ids=["spiffe://penguintech.io/backend"],
        )
        assert cfg.trust_domain == "penguintech.io"
        assert cfg.workload_socket == "/run/spire/agent.sock"
        assert len(cfg.allowed_ids) == 1

    def test_empty_trust_domain_raises(self):
        with pytest.raises(ValueError, match="trust_domain must not be empty"):
            SPIFFEConfig(
                trust_domain="  ",
                workload_socket="/run/spire/agent.sock",
            )

    def test_empty_workload_socket_raises(self):
        with pytest.raises(ValueError, match="workload_socket must not be empty"):
            SPIFFEConfig(
                trust_domain="penguintech.io",
                workload_socket="",
            )

    def test_invalid_allowed_id_raises(self):
        with pytest.raises(ValueError):
            SPIFFEConfig(
                trust_domain="penguintech.io",
                workload_socket="/run/spire/agent.sock",
                allowed_ids=["not-a-spiffe-id"],
            )

    def test_default_allowed_ids_empty(self):
        cfg = SPIFFEConfig(
            trust_domain="penguintech.io",
            workload_socket="/run/spire/agent.sock",
        )
        assert cfg.allowed_ids == []


class TestSPIFFEAuthenticator:
    def _make_authenticator(self, allowed_ids=None):
        cfg = SPIFFEConfig(
            trust_domain="penguintech.io",
            workload_socket="/run/spire/agent.sock",
            allowed_ids=allowed_ids or [],
        )
        return SPIFFEAuthenticator(cfg)

    def test_validate_peer_id_allowed(self):
        auth = self._make_authenticator(
            allowed_ids=["spiffe://penguintech.io/backend"],
        )
        assert auth.validate_peer_id("spiffe://penguintech.io/backend") is True

    def test_validate_peer_id_not_in_allowlist(self):
        auth = self._make_authenticator(
            allowed_ids=["spiffe://penguintech.io/backend"],
        )
        assert auth.validate_peer_id("spiffe://penguintech.io/frontend") is False

    def test_validate_peer_id_empty_allowlist_denies(self):
        auth = self._make_authenticator(allowed_ids=[])
        assert auth.validate_peer_id("spiffe://penguintech.io/backend") is False

    def test_validate_peer_id_invalid_spiffe_id(self):
        auth = self._make_authenticator(
            allowed_ids=["spiffe://penguintech.io/backend"],
        )
        assert auth.validate_peer_id("not-valid") is False

    def test_is_same_trust_domain_true(self):
        auth = self._make_authenticator()
        assert auth.is_same_trust_domain("spiffe://penguintech.io/service") is True

    def test_is_same_trust_domain_false(self):
        auth = self._make_authenticator()
        assert auth.is_same_trust_domain("spiffe://other.io/service") is False

    def test_is_same_trust_domain_invalid_id(self):
        auth = self._make_authenticator()
        assert auth.is_same_trust_domain("invalid-id") is False
