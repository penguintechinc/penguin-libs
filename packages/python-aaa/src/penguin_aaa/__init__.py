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
from penguin_aaa.endpoints.flask_bp import create_oidc_blueprint
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
