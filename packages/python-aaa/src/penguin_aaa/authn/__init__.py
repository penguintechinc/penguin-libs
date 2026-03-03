"""Authentication subpackage — OIDC RP, OIDC Provider, SPIFFE, and types."""

from penguin_aaa.authn.oidc_provider import OIDCProvider, OIDCProviderConfig
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty, OIDCRPConfig
from penguin_aaa.authn.spiffe import SPIFFEAuthenticator, SPIFFEConfig
from penguin_aaa.authn.types import (
    ALLOWED_PROVIDER_ALGORITHMS,
    ALLOWED_RP_ALGORITHMS,
    MAX_SUBJECT_LENGTH,
    MAX_TOKEN_SIZE,
    Claims,
    TokenSet,
)

__all__ = [
    "Claims",
    "TokenSet",
    "MAX_SUBJECT_LENGTH",
    "MAX_TOKEN_SIZE",
    "ALLOWED_RP_ALGORITHMS",
    "ALLOWED_PROVIDER_ALGORITHMS",
    "OIDCRPConfig",
    "OIDCRelyingParty",
    "OIDCProviderConfig",
    "OIDCProvider",
    "SPIFFEConfig",
    "SPIFFEAuthenticator",
]
