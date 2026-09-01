"""IP address utilities: client-IP extraction and private-range detection.

Private/internal sources are never rate-limited — the check happens before any
storage or algorithm call, keeping the hot path fast for internal traffic.

Trust model (security-critical)
--------------------------------
``X-Forwarded-For`` and ``X-Real-IP`` are attacker-controllable — any client
can set them to whatever value it wants on the very first hop. Honouring them
unconditionally lets an attacker forge a private-looking address (e.g.
``X-Forwarded-For: 10.0.0.1``) and trigger the private-IP rate-limit bypass
even though the real, direct peer is a public address.

Default (``trusted_proxy_count=0``): forwarded headers are **never trusted**.
Only the direct transport peer address (``remote_addr`` / gRPC ``peer()`` /
QUIC source address) is used. This is safe with zero configuration.

When a known number of trusted reverse proxies sit in front of this service
(e.g. an in-cluster ingress), set ``trusted_proxy_count`` to that count. Each
trusted hop is expected to *append* the address it observed to the right end
of ``X-Forwarded-For`` — so the true client address is always the entry
``trusted_proxy_count`` positions from the right (``values[-trusted_proxy_count]``,
the well-established `Werkzeug ProxyFix
<https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/>`_ /
Express ``trust proxy`` convention). Any hops an attacker prepends further
left are ignored — they can never shift a trusted, proxy-appended entry out
of its position from the right.
"""

from __future__ import annotations

import ipaddress

# ---------------------------------------------------------------------------
# Private / reserved ranges
# ---------------------------------------------------------------------------

_PRIVATE_V4: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),  # RFC 1918 class-A
    ipaddress.IPv4Network("172.16.0.0/12"),  # RFC 1918 class-B
    ipaddress.IPv4Network("192.168.0.0/16"),  # RFC 1918 class-C
    ipaddress.IPv4Network("127.0.0.0/8"),  # loopback
    ipaddress.IPv4Network("169.254.0.0/16"),  # link-local (APIPA)
    ipaddress.IPv4Network("100.64.0.0/10"),  # carrier-grade NAT (RFC 6598)
    ipaddress.IPv4Network("0.0.0.0/8"),  # "this" network
)

_PRIVATE_V6: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::1/128"),  # loopback
    ipaddress.IPv6Network("fc00::/7"),  # unique local (ULA)
    ipaddress.IPv6Network("fe80::/10"),  # link-local
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped
    ipaddress.IPv6Network("64:ff9b::/96"),  # IPv4-translated (NAT64)
)


def is_private_ip(ip_str: str) -> bool:
    """Return ``True`` if *ip_str* is a private / reserved address.

    Malformed strings are treated as *private* (safe default — if we cannot
    parse the address we should not apply rate limiting based on it).
    """
    ip_str = ip_str.strip()
    # Strip IPv6 zone ID (e.g. "fe80::1%eth0")
    if "%" in ip_str:
        ip_str = ip_str.split("%")[0]
    # Strip port if present in bracket notation [::1]:port
    if ip_str.startswith("["):
        ip_str = ip_str[1:].split("]")[0]
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → treat as private / skip rate limit

    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _PRIVATE_V4)
    return any(addr in net for net in _PRIVATE_V6)


def _strip_port(candidate: str) -> str:
    """Strip a trailing ``:port`` from a bare IPv4 address (not bracketed IPv6)."""
    if ":" in candidate and not candidate.startswith("[") and candidate.count(":") == 1:
        return candidate.rsplit(":", 1)[0]
    return candidate


def _resolve_trusted_forwarded_for(header_value: str, trusted_proxy_count: int) -> str | None:
    """Resolve the true client address from a trusted ``X-Forwarded-For`` chain.

    Each trusted proxy appends the address it observed to the right end of
    the header. With *trusted_proxy_count* trusted hops, the true client is
    the entry ``trusted_proxy_count`` positions from the right — any entries
    further left (including attacker-prepended ones) are untrusted and
    ignored. Returns ``None`` if the header doesn't contain enough hops to
    satisfy *trusted_proxy_count* (misconfiguration — fail closed to the next
    lower-priority source rather than guessing).
    """
    hops = [h.strip() for h in header_value.split(",") if h.strip()]
    if trusted_proxy_count <= 0 or len(hops) < trusted_proxy_count:
        return None
    return hops[-trusted_proxy_count]


def extract_client_ip(
    x_forwarded_for: str | None = None,
    x_real_ip: str | None = None,
    remote_addr: str | None = None,
    *,
    trusted_proxy_count: int = 0,
) -> str | None:
    """Determine the real client IP from available request metadata.

    Parameters
    ----------
    x_forwarded_for:
        Value of the ``X-Forwarded-For`` header. Only consulted when
        *trusted_proxy_count* > 0 — see module docstring Trust model.
    x_real_ip:
        Value of the ``X-Real-IP`` header set by a single trusted proxy.
        Only consulted when *trusted_proxy_count* > 0.
    remote_addr:
        The TCP-level source address of the direct sender. Always used when
        forwarded headers are untrusted or absent — the safe fallback.
    trusted_proxy_count:
        Number of trusted reverse proxies known to sit directly in front of
        this service. ``0`` (default) means forwarded headers are never
        trusted, regardless of whether they're present.

    Returns ``None`` if no address could be resolved at all.
    """
    if trusted_proxy_count > 0:
        if x_forwarded_for:
            resolved = _resolve_trusted_forwarded_for(x_forwarded_for, trusted_proxy_count)
            if resolved:
                return resolved
        if x_real_ip:
            candidate = x_real_ip.strip()
            if candidate:
                return candidate

    if remote_addr:
        candidate = _strip_port(remote_addr.strip())
        if candidate:
            return candidate

    return None


def should_rate_limit(
    x_forwarded_for: str | None = None,
    x_real_ip: str | None = None,
    remote_addr: str | None = None,
    *,
    trusted_proxy_count: int = 0,
) -> tuple[bool, str | None]:
    """Return ``(should_limit, client_ip)``.

    ``client_ip`` is resolved per the trust model in :func:`extract_client_ip`
    — never a raw, unverified header value. ``should_limit`` is ``False``
    only when that resolved (trustworthy) address is private/internal,
    meaning the request genuinely originates from within the cluster or a
    trusted network — never because an attacker claimed so via a header.
    """
    client_ip = extract_client_ip(
        x_forwarded_for,
        x_real_ip,
        remote_addr,
        trusted_proxy_count=trusted_proxy_count,
    )
    if client_ip is None:
        return False, None
    return not is_private_ip(client_ip), client_ip
