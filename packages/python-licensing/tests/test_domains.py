"""Tests for the shared domain-based license bypass matcher."""

import pytest

from penguin_licensing.domains import BYPASS_DOMAINS, is_bypass_domain


class TestIsBypassDomain:
    """Bypass is host-driven only; these tests pin the exact matching rules."""

    @pytest.mark.parametrize(
        "host",
        [
            "elder.penguincloud.io",
            "penguincloud.io",
            "waddlebot.penguintech.cloud",
            "penguintech.cloud",
            "squawk.localhost.local",
            "ELDER.PENGUINCLOUD.IO",
            "elder.penguincloud.io:8443",
        ],
    )
    def test_builtin_domains_match(self, host):
        """Managed hosts match on a dot boundary, case- and port-insensitively."""
        assert is_bypass_domain(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "evil-penguintech.cloud",
            "penguintech.cloud.attacker.com",
            "evilpenguincloud.io",
            "penguincloud.io.attacker.test",
            "notpenguintech.cloud",
            "example.com",
            "localhost",
            "",
        ],
    )
    def test_non_bypass_domains_do_not_match(self, host):
        """Look-alike hosts must never slip past the dot-boundary check."""
        assert is_bypass_domain(host) is False

    def test_no_host_is_not_bypassed(self):
        """A falsy host always falls through to the normal licence flow."""
        assert is_bypass_domain("") is False
        assert is_bypass_domain(None) is False  # type: ignore[arg-type]

    def test_host_that_is_only_a_port_is_not_bypassed(self):
        """A host that normalizes to empty (e.g. just a port) is not bypassed."""
        assert is_bypass_domain(":8443") is False

    def test_blank_extra_domain_entries_are_skipped(self):
        """An empty/whitespace-only extra domain is ignored, not a wildcard match."""
        assert is_bypass_domain("example.com", extra_domains=["", "   "]) is False

    def test_extra_domains_match_as_subdomain_and_apex(self):
        """A caller-supplied product domain matches like a built-in one."""
        assert is_bypass_domain("app.waddleai.app", extra_domains=["waddleai.app"]) is True
        assert is_bypass_domain("waddleai.app", extra_domains=["waddleai.app"]) is True

    def test_extra_domains_still_respect_dot_boundary(self):
        """A look-alike host must not match an extra domain either."""
        assert is_bypass_domain("evil-waddleai.app", extra_domains=["waddleai.app"]) is False
        assert (
            is_bypass_domain("waddleai.app.attacker.test", extra_domains=["waddleai.app"])
            is False
        )

    def test_extra_domains_do_not_widen_builtin_domains(self):
        """Passing extra domains must not affect matching against unrelated hosts."""
        assert is_bypass_domain("example.com", extra_domains=["waddleai.app"]) is False

    def test_builtin_domains_are_dot_prefixed(self):
        """Every built-in entry is a subdomain-suffix, not a bare apex only."""
        assert all(domain.startswith(".") for domain in BYPASS_DOMAINS)
