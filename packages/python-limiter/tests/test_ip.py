"""Tests for IP detection, private-range classification, and the
trusted-proxy forwarded-header trust model.

Regression coverage for the HIGH finding: prior to the fix,
``X-Forwarded-For`` / ``X-Real-IP`` were trusted unconditionally, letting an
attacker forge a private-looking address and trigger the private-IP
rate-limit bypass. The fix requires forwarded headers to be explicitly
enabled via ``trusted_proxy_count`` and resolves the true client using the
Werkzeug-ProxyFix-style right-to-left trusted-hop convention.
"""

from __future__ import annotations

import pytest

from penguin_limiter.ip import extract_client_ip, is_private_ip, should_rate_limit


class TestIsPrivateIp:
    # RFC 1918
    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.254",
            "127.0.0.1",
            "127.1.2.3",
            "169.254.0.1",  # link-local
            "100.64.0.1",  # carrier-grade NAT
            "::1",  # IPv6 loopback
            "fc00::1",  # ULA
            "fe80::1",  # IPv6 link-local
            "::ffff:192.168.1.1",  # IPv4-mapped
        ],
    )
    def test_private_addresses(self, ip: str) -> None:
        assert is_private_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "1.2.3.4",
            "8.8.8.8",
            "203.0.113.5",
            "2001:db8::1",
            "2606:4700::1",
        ],
    )
    def test_public_addresses(self, ip: str) -> None:
        assert is_private_ip(ip) is False

    def test_malformed_address_treated_as_private(self) -> None:
        assert is_private_ip("not-an-ip") is True
        assert is_private_ip("") is True
        assert is_private_ip("999.999.999.999") is True

    def test_ipv6_with_zone_id(self) -> None:
        # fe80::1%eth0 — link-local, private
        assert is_private_ip("fe80::1%eth0") is True

    def test_bracket_notation(self) -> None:
        # Some proxies write [::1] or [::1]:port
        assert is_private_ip("[::1]") is True


class TestExtractClientIpDefaultUntrusted:
    """Default (trusted_proxy_count=0): forwarded headers are never trusted."""

    def test_xff_ignored_falls_back_to_remote_addr(self) -> None:
        ip = extract_client_ip(x_forwarded_for="1.2.3.4", remote_addr="9.9.9.9")
        assert ip == "9.9.9.9"

    def test_xff_forged_private_does_not_override_public_remote_addr(self) -> None:
        # regression: attacker-forged XFF must never be honored by default
        ip = extract_client_ip(x_forwarded_for="10.0.0.1", remote_addr="8.8.8.8")
        assert ip == "8.8.8.8"

    def test_xri_ignored_falls_back_to_remote_addr(self) -> None:
        ip = extract_client_ip(x_real_ip="203.0.113.1", remote_addr="5.5.5.5")
        assert ip == "5.5.5.5"

    def test_remote_addr_used_as_only_source(self) -> None:
        ip = extract_client_ip(remote_addr="8.8.4.4")
        assert ip == "8.8.4.4"

    def test_remote_addr_with_port_stripped(self) -> None:
        ip = extract_client_ip(remote_addr="1.2.3.4:54321")
        assert ip == "1.2.3.4"

    def test_no_addresses_returns_none(self) -> None:
        assert extract_client_ip() is None

    def test_xff_only_no_remote_addr_returns_none(self) -> None:
        # Without a trusted proxy count, XFF alone resolves nothing.
        assert extract_client_ip(x_forwarded_for="1.2.3.4") is None


class TestExtractClientIpTrustedProxy:
    """trusted_proxy_count > 0: forwarded headers honored per the
    right-to-left trusted-hop convention (Werkzeug ProxyFix / Express
    'trust proxy')."""

    def test_single_trusted_proxy_uses_rightmost_hop(self) -> None:
        ip = extract_client_ip(x_forwarded_for="1.2.3.4", trusted_proxy_count=1)
        assert ip == "1.2.3.4"

    def test_single_trusted_proxy_ignores_attacker_prepended_hops(self) -> None:
        # Attacker prepends fake hops on the left; the trusted proxy still
        # appends the real client IP as the rightmost entry.
        ip = extract_client_ip(
            x_forwarded_for="10.0.0.1, 6.6.6.6, 1.2.3.4",
            trusted_proxy_count=1,
        )
        assert ip == "1.2.3.4"

    def test_two_trusted_proxies_uses_second_from_right(self) -> None:
        # proxy1 appended "1.2.3.4" (real client), proxy2 appended proxy1's
        # own address "10.0.0.5" as the rightmost entry.
        ip = extract_client_ip(
            x_forwarded_for="1.2.3.4, 10.0.0.5",
            trusted_proxy_count=2,
        )
        assert ip == "1.2.3.4"

    def test_insufficient_hops_falls_back_to_remote_addr(self) -> None:
        # trusted_proxy_count=2 but header only has 1 hop — misconfiguration,
        # fail closed to the direct peer rather than guessing.
        ip = extract_client_ip(
            x_forwarded_for="1.2.3.4",
            remote_addr="9.9.9.9",
            trusted_proxy_count=2,
        )
        assert ip == "9.9.9.9"

    def test_xri_used_when_trusted_and_no_xff(self) -> None:
        ip = extract_client_ip(x_real_ip="203.0.113.1", trusted_proxy_count=1)
        assert ip == "203.0.113.1"

    def test_xff_preferred_over_xri_when_both_present(self) -> None:
        ip = extract_client_ip(
            x_forwarded_for="1.2.3.4",
            x_real_ip="9.9.9.9",
            trusted_proxy_count=1,
        )
        assert ip == "1.2.3.4"


class TestShouldRateLimit:
    def test_public_ip_should_limit(self) -> None:
        do_limit, ip = should_rate_limit(remote_addr="1.2.3.4")
        assert do_limit is True
        assert ip == "1.2.3.4"

    def test_private_ip_should_not_limit(self) -> None:
        do_limit, ip = should_rate_limit(remote_addr="10.0.0.5")
        assert do_limit is False
        assert ip == "10.0.0.5"

    def test_no_address_should_not_limit(self) -> None:
        do_limit, ip = should_rate_limit()
        assert do_limit is False
        assert ip is None

    # --- Regression: HIGH finding — trusted-proxy IP spoofing bypass -----

    def test_forged_xff_private_ip_does_not_bypass_when_peer_is_public(self) -> None:
        """(a) Default config: a public peer sending a forged private
        X-Forwarded-For must still be rate-limited — the bypass must not
        fire based on an untrusted, client-supplied header."""
        do_limit, ip = should_rate_limit(
            x_forwarded_for="10.0.0.1",
            remote_addr="8.8.8.8",
        )
        assert do_limit is True
        assert ip == "8.8.8.8"

    def test_forged_xff_multiple_private_hops_still_public_peer(self) -> None:
        # Attacker supplies an entire chain of private-looking hops; with no
        # trusted_proxy_count configured none of it is honored.
        do_limit, ip = should_rate_limit(
            x_forwarded_for="10.0.0.1, 192.168.1.1, 127.0.0.1",
            remote_addr="1.2.3.4",
        )
        assert do_limit is True
        assert ip == "1.2.3.4"

    def test_trusted_proxy_correctly_identifies_private_client(self) -> None:
        """(c) With trusted_proxy_count=1, a genuine private client behind
        one trusted proxy is correctly identified and bypassed."""
        do_limit, ip = should_rate_limit(
            x_forwarded_for="192.168.1.50",
            remote_addr="10.0.0.1",  # the trusted proxy's own address
            trusted_proxy_count=1,
        )
        assert do_limit is False
        assert ip == "192.168.1.50"

    def test_trusted_proxy_extra_fake_hops_cannot_force_private(self) -> None:
        """(d) An attacker prepending extra fake hops beyond the trusted
        count cannot force a private classification."""
        do_limit, ip = should_rate_limit(
            x_forwarded_for="10.0.0.1, 192.168.1.1, 8.8.8.8",
            remote_addr="10.0.0.99",
            trusted_proxy_count=1,
        )
        assert do_limit is True
        assert ip == "8.8.8.8"

    def test_trusted_proxy_rejects_forged_public_identity_claim(self) -> None:
        """Sharpest regression demonstration of the root cause: without a
        trusted-hop count, ANY client-supplied XFF entry (public-looking or
        private-looking) was trusted at face value. Here the attacker claims
        to *be* a specific public IP (1.2.3.4) that isn't theirs; the
        trusted proxy appends the address it actually observed (8.8.8.8).

        Before the fix: ``extract_client_ip`` walked left-to-right and
        returned the first non-private entry — the attacker's forged claim
        ``1.2.3.4`` — using it as the rate-limit key instead of the real
        client. That lets an attacker evade their own limit indefinitely
        (claim a new public IP each request) or exhaust another IP's quota.
        After the fix, with ``trusted_proxy_count=1``, only the entry
        actually appended by the trusted proxy is honored.
        """
        do_limit, ip = should_rate_limit(
            x_forwarded_for="1.2.3.4, 8.8.8.8",
            remote_addr="10.0.0.99",
            trusted_proxy_count=1,
        )
        assert do_limit is True
        assert ip == "8.8.8.8"
