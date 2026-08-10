"""PenguinTech Authentication, Authorization, and Accounting library."""

from penguin_aaa.authn.multi_issuer import (
    ClaimsMapping,
    MultiIssuerRelyingParty,
    UpstreamProvider,
)
from penguin_aaa.authn.oidc_provider import OIDCProvider
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, generate_pkce_pair
from penguin_aaa.authn.presets import okta_provider, skauswatch_provider
from penguin_aaa.authn.types import Claims, TokenSet
from penguin_aaa.crypto.keystore import FileKeyStore, KeyStore, MemoryKeyStore
from penguin_aaa.token_store.base import TokenStore
from penguin_aaa.token_store.memory import MemoryTokenStore

__all__ = [
    "Claims",
    "TokenSet",
    "OIDCRelyingParty",
    "OIDCProvider",
    "KeyStore",
    "MemoryKeyStore",
    "FileKeyStore",
    "TokenStore",
    "MemoryTokenStore",
    "generate_pkce_pair",
    "create_oidc_blueprint",
    "MultiIssuerRelyingParty",
    "UpstreamProvider",
    "ClaimsMapping",
    "okta_provider",
    "skauswatch_provider",
]


def __getattr__(name: str) -> object:
    """Lazy-load Flask blueprint import (optional dependency)."""
    if name == "create_oidc_blueprint":
        try:
            from penguin_aaa.endpoints.flask_bp import create_oidc_blueprint
            return create_oidc_blueprint
        except ImportError as e:
            raise ImportError(
                "create_oidc_blueprint requires the 'flask' extra: pip install penguin-aaa[flask]"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
