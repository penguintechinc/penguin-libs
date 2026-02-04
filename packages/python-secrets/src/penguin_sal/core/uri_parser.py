"""URI parser for penguin-sal connection strings.

Parses connection URIs in the format:
    scheme://[user:pass@]host[:port][/path][?params]

Each backend interprets components differently:
- Vault: host+port = server, path = mount point, query = auth params
- AWS SM: host = region, query = profile/role
- K8s: host = namespace, query = context/kubeconfig
- 1Password: host = connect server, path = vault name
- Passbolt: host = server, query = PGP key path + passphrase
"""

from __future__ import annotations

from typing import NamedTuple
from urllib.parse import parse_qs, unquote, urlparse

from penguin_sal.core.exceptions import InvalidURIError

SUPPORTED_SCHEMES: frozenset[str] = frozenset(
    {
        "vault",
        "infisical",
        "cyberark",
        "aws-sm",
        "gcp-sm",
        "azure-kv",
        "oci-vault",
        "k8s",
        "1password",
        "passbolt",
        "doppler",
    }
)


class ParsedURI(NamedTuple):
    """Parsed components of a secrets backend URI."""

    scheme: str
    host: str
    port: int | None
    path: str
    username: str | None
    password: str | None
    params: dict[str, str]


def parse_uri(uri: str) -> ParsedURI:
    """Parse a secrets backend connection URI.

    Args:
        uri: Connection string in format scheme://[user:pass@]host[:port][/path][?params]

    Returns:
        ParsedURI with parsed components.

    Raises:
        InvalidURIError: If the URI is malformed or uses an unsupported scheme.
    """
    if not uri or not isinstance(uri, str):
        raise InvalidURIError(str(uri), "URI must be a non-empty string")

    # Find scheme separator
    scheme_sep = uri.find("://")
    if scheme_sep == -1:
        raise InvalidURIError(uri, "missing scheme (expected scheme://...)")

    scheme = uri[:scheme_sep].lower()

    if scheme not in SUPPORTED_SCHEMES:
        raise InvalidURIError(
            uri,
            f"unsupported scheme '{scheme}', "
            f"must be one of: {', '.join(sorted(SUPPORTED_SCHEMES))}",
        )

    # Normalize URI for urlparse - replace custom schemes with https
    normalized = "https" + uri[scheme_sep:]
    try:
        parsed = urlparse(normalized)
    except Exception as e:
        raise InvalidURIError(uri, f"failed to parse: {e}") from e

    host = unquote(parsed.hostname or "")
    port = parsed.port
    path = unquote(parsed.path).strip("/") if parsed.path else ""
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    # Parse query parameters - take first value for each key
    raw_params = parse_qs(parsed.query, keep_blank_values=True)
    params: dict[str, str] = {k: v[0] for k, v in raw_params.items()}

    return ParsedURI(
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        username=username,
        password=password,
        params=params,
    )
