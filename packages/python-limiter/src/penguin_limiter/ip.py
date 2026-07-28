"""IP address utilities: client-IP extraction and private-range detection.

Private/internal sources are never rate-limited — the check happens before any
storage or algorithm call, keeping the hot path fast for internal traffic.

Detection priority
------------------
1. ``X-Forwarded-For`` — walk left to right, return the **first non-private** IP.
   A chain like ``10.0.0.1, 1.2.3.4`` means the real client is ``1.2.3.4``.
2. ``X-Real-IP`` — single hop set by the outermost proxy.
3. ``remote_addr`` — the TCP source address of the immediate sender.
"""

from __future__ import annotations

import ipaddress

# ---------------------------------------------------------------------------
# Private / reserved ranges
# ---------------------------------------------------------------------------

_PRIVATE_V4: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),        # RFC 1918 class-A
    ipaddress.IPv4Network("172.16.0.0/12"),     # RFC 1918 class-B
    ipaddress.IPv4Network("192.168.0.0/16"),    # RFC 1918 class-C
    ipaddress.IPv4Network("127.0.0.0/8"),       # loopback
    ipaddress.IPv4Network("169.254.0.0/16"),    # link-local (APIPA)
    ipaddress.IPv4Network("100.64.0.0/10"),     # carrier-grade NAT (RFC 6598)
    ipaddress.IPv4Network("0.0.0.0/8"),         # "this" network
)

_PRIVATE_V6: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::1/128"),           # loopback
    ipaddress.IPv6Network("fc00::/7"),          # unique local (ULA)
    ipaddress.IPv6Network("fe80::/10"),         # link-local
    ipaddress.IPv6Network("::ffff:0:0/96"),     # IPv4-mapped
    ipaddress.IPv6Network("64:ff9b::/96"),      # IPv4-translated (NAT64)
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


def extract_client_ip(
    x_forwarded_for: str | None = None,
    x_real_ip: str | None = None,
    remote_addr: str | None = None,
) -> str | None:
    """Determine the real external client IP from available request metadata.

    Returns ``None`` if only private / unroutable addresses are found, which
    signals the caller to **skip rate limiting** for this request.

    Parameters
    ----------
    x_forwarded_for:
        Value of the ``X-Forwarded-For`` header (may contain a comma-separated
        list of IPs added by successive proxies).
    x_real_ip:
        Value of the ``X-Real-IP`` header set by a single trusted proxy.
    remote_addr:
        The TCP-level source address of the direct sender.
    """
    if x_forwarded_for:
        for part in x_forwarded_for.split(","):
            candidate = part.strip()
            if candidate and not is_private_ip(candidate):
                return candidate

    if x_real_ip:
        candidate = x_real_ip.strip()
        if candidate and not is_private_ip(candidate):
            return candidate

    if remote_addr:
        candidate = remote_addr.strip()
        # Strip port suffix "1.2.3.4:56789"
        if ":" in candidate and not candidate.startswith("[") and candidate.count(":") == 1:
            candidate = candidate.rsplit(":", 1)[0]
        if candidate and not is_private_ip(candidate):
            return candidate

    return None  # all addresses are private → skip rate limiting


def should_rate_limit(
    x_forwarded_for: str | None = None,
    x_real_ip: str | None = None,
    remote_addr: str | None = None,
) -> tuple[bool, str | None]:
    """Return ``(should_limit, client_ip)``.

    ``should_limit`` is ``False`` when the resolved IP is private/internal,
    meaning the request comes from within the cluster or a trusted network.
    """
    client_ip = extract_client_ip(x_forwarded_for, x_real_ip, remote_addr)
    return client_ip is not None, client_ip
