"""Domain-based license bypass.

Managed PenguinTech deployments (PenguinCloud, the beta/dev cluster, and each
product's own alpha/local domain) are billed and operated by PenguinTech
directly, so per-call license-server round trips are skipped for them. Bypass
is domain-driven only -- there is deliberately no environment variable, CLI
flag, or config toggle that can disable license enforcement; see
critical-rules.md Feature Flags & License Tiers. This module is the single
source of truth for the domain match so ``LicenseClient`` and the
``license_required``/``feature_required`` decorators can never disagree on
what counts as a managed domain.
"""

from collections.abc import Sequence

# Domains PenguinTech operates directly. A leading "." matches only as a
# subdomain suffix (see is_bypass_domain) plus the bare apex; entries without
# one match only that exact host.
BYPASS_DOMAINS: tuple[str, ...] = (
    ".penguincloud.io",
    ".penguintech.cloud",
    ".localhost.local",
)


def is_bypass_domain(host: str, extra_domains: Sequence[str] = ()) -> bool:
    """
    Return True when host is a managed domain that skips license checks.

    Matches on a dot boundary only, so ``evil-penguintech.cloud`` never
    matches ``.penguintech.cloud`` and ``penguintech.cloud.attacker.test``
    never matches either -- both stay ordinary, license-gated hosts. The bare
    apex of a bypass domain (e.g. ``penguintech.cloud`` itself) does match.

    ``extra_domains`` lets a caller add its own product domain (e.g.
    ``waddleai.app``) without hardcoding every product here; entries are
    matched with the same dot-boundary rule as ``BYPASS_DOMAINS``.
    """
    if not host:
        return False
    normalized = host.split(":", 1)[0].strip().lower().rstrip(".")
    if not normalized:
        return False
    for domain in (*BYPASS_DOMAINS, *extra_domains):
        candidate = domain.strip().lower()
        if not candidate:
            continue
        bare = candidate.lstrip(".")
        suffix = candidate if candidate.startswith(".") else f".{candidate}"
        if normalized == bare or normalized.endswith(suffix):
            return True
    return False


__all__ = ["BYPASS_DOMAINS", "is_bypass_domain"]
