"""Security-hardening validators for authentication configuration fields."""

from urllib.parse import urlparse


def validate_https_url(url: str, field_name: str) -> None:
    """
    Validate that a URL uses the HTTPS scheme.

    Localhost URLs (127.0.0.1, ::1, localhost) are accepted with either
    HTTP or HTTPS to facilitate local development and testing.

    Args:
        url: The URL string to validate.
        field_name: Field name to include in error messages.

    Raises:
        ValueError: If the URL is empty, malformed, or uses a non-HTTPS
                    scheme for non-localhost hosts.
    """
    if not url or not url.strip():
        raise ValueError(f"{field_name} must not be empty")

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{field_name} must be a fully-qualified URL, got: {url!r}")

    hostname = parsed.hostname or ""
    is_localhost = hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".localhost")

    if not is_localhost and parsed.scheme != "https":
        raise ValueError(
            f"{field_name} must use HTTPS for non-localhost URLs, got scheme: {parsed.scheme!r}"
        )


def validate_spiffe_id(spiffe_id: str) -> None:
    """
    Validate that a SPIFFE ID conforms to the spiffe:// URI scheme.

    Args:
        spiffe_id: The SPIFFE ID string to validate.

    Raises:
        ValueError: If the ID does not start with "spiffe://" or is malformed.
    """
    if not spiffe_id or not spiffe_id.strip():
        raise ValueError("SPIFFE ID must not be empty")

    if not spiffe_id.startswith("spiffe://"):
        raise ValueError(
            f"SPIFFE ID must start with 'spiffe://', got: {spiffe_id!r}"
        )

    # spiffe://trust-domain/...  — trust domain must be non-empty
    remainder = spiffe_id[len("spiffe://"):]
    if not remainder or remainder.startswith("/"):
        raise ValueError(
            f"SPIFFE ID must include a non-empty trust domain after 'spiffe://', got: {spiffe_id!r}"
        )


def validate_algorithm(alg: str, allowed: frozenset[str]) -> None:
    """
    Validate a cryptographic algorithm identifier against an allowlist.

    Always rejects "none" and "HS256" to prevent algorithm confusion attacks.

    Args:
        alg: The algorithm string to validate (e.g. "RS256").
        allowed: Frozenset of permitted algorithm strings.

    Raises:
        ValueError: If the algorithm is explicitly forbidden or not in the
                    allowed set.
    """
    explicitly_forbidden = {"none", "HS256"}
    if alg in explicitly_forbidden:
        raise ValueError(
            f"Algorithm {alg!r} is explicitly forbidden for security reasons"
        )

    if alg not in allowed:
        raise ValueError(
            f"Algorithm {alg!r} is not in the permitted set: {sorted(allowed)}"
        )
