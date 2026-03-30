"""Tests for IP detection and private-range classification."""

from __future__ import annotations

import pytest

from penguin_limiter.ip import extract_client_ip, is_private_ip, should_rate_limit


class TestIsPrivateIp:
    # RFC 1918
    @pytest.mark.parametrize("ip", [
        "10.0.0.1", "10.255.255.255",
        "172.16.0.1", "172.31.255.255",
        "192.168.0.1", "192.168.255.254",
        "127.0.0.1", "127.1.2.3",
        "169.254.0.1",  # link-local
        "100.64.0.1",   # carrier-grade NAT
        "::1",          # IPv6 loopback
        "fc00::1",      # ULA
        "fe80::1",      # IPv6 link-local
        "::ffff:192.168.1.1",  # IPv4-mapped
    ])
    def test_private_addresses(self, ip: str) -> None:
        assert is_private_ip(ip) is True

    @pytest.mark.parametrize("ip", [
        "1.2.3.4",
        "8.8.8.8",
        "203.0.113.5",
        "2001:db8::1",
        "2606:4700::1",
    ])
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


class TestExtractClientIp:
    def test_xff_public_ip_returned(self) -> None:
        ip = extract_client_ip(x_forwarded_for="1.2.3.4")
        assert ip == "1.2.3.4"

    def test_xff_skips_private_takes_first_public(self) -> None:
        # Chain: internal proxy → real client
        ip = extract_client_ip(x_forwarded_for="10.0.0.1, 1.2.3.4, 5.6.7.8")
        assert ip == "1.2.3.4"

    def test_xff_all_private_falls_through_to_xri(self) -> None:
        ip = extract_client_ip(
            x_forwarded_for="10.0.0.1, 192.168.1.1",
            x_real_ip="203.0.113.99",
        )
        assert ip == "203.0.113.99"

    def test_xri_used_when_no_xff(self) -> None:
        ip = extract_client_ip(x_real_ip="203.0.113.1")
        assert ip == "203.0.113.1"

    def test_xri_private_falls_through_to_remote_addr(self) -> None:
        ip = extract_client_ip(x_real_ip="192.168.1.1", remote_addr="5.5.5.5")
        assert ip == "5.5.5.5"

    def test_remote_addr_used_as_last_resort(self) -> None:
        ip = extract_client_ip(remote_addr="8.8.4.4")
        assert ip == "8.8.4.4"

    def test_remote_addr_with_port_stripped(self) -> None:
        ip = extract_client_ip(remote_addr="1.2.3.4:54321")
        assert ip == "1.2.3.4"

    def test_all_private_returns_none(self) -> None:
        ip = extract_client_ip(
            x_forwarded_for="10.0.0.1",
            x_real_ip="192.168.1.1",
            remote_addr="127.0.0.1",
        )
        assert ip is None

    def test_no_headers_returns_none(self) -> None:
        assert extract_client_ip() is None


class TestShouldRateLimit:
    def test_public_ip_should_limit(self) -> None:
        do_limit, ip = should_rate_limit(remote_addr="1.2.3.4")
        assert do_limit is True
        assert ip == "1.2.3.4"

    def test_private_ip_should_not_limit(self) -> None:
        do_limit, ip = should_rate_limit(remote_addr="10.0.0.5")
        assert do_limit is False
        assert ip is None

    def test_xff_public_should_limit(self) -> None:
        do_limit, ip = should_rate_limit(
            x_forwarded_for="10.0.0.1, 203.0.113.5",
            remote_addr="10.0.0.1",
        )
        assert do_limit is True
        assert ip == "203.0.113.5"
