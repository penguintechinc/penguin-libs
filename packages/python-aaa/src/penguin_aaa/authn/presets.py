"""Preset factory helpers for common upstream OIDC providers."""

from penguin_aaa.authn.multi_issuer import ClaimsMapping, UpstreamProvider
from penguin_aaa.authn.oidc_rp import OIDCRPConfig


def okta_provider(
    issuer_url: str,
    client_id: str,
    client_secret: str,
    redirect_url: str,
) -> UpstreamProvider:
    """
    Pre-configured UpstreamProvider for Okta.

    Maps Okta's 'groups' claim to 'roles' and 'tid' to 'tenant'.

    Args:
        issuer_url: Okta authorization server URL.
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        redirect_url: OAuth2 redirect URI.

    Returns:
        UpstreamProvider configured for Okta.
    """
    return UpstreamProvider(
        name="okta",
        config=OIDCRPConfig(
            issuer_url=issuer_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_url=redirect_url,
            scopes=["openid", "profile", "email", "groups"],
        ),
        claims_mapping=ClaimsMapping(
            roles_claim="groups",
            tenant_claim="tid",
        ),
    )


def skauswatch_provider(
    issuer_url: str,
    client_id: str,
    client_secret: str,
    redirect_url: str,
) -> UpstreamProvider:
    """
    Pre-configured UpstreamProvider for SkausWatch.

    Uses standard OIDC claim names (no custom mappings needed).

    Args:
        issuer_url: SkausWatch authorization server URL.
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        redirect_url: OAuth2 redirect URI.

    Returns:
        UpstreamProvider configured for SkausWatch.
    """
    return UpstreamProvider(
        name="skauswatch",
        config=OIDCRPConfig(
            issuer_url=issuer_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_url=redirect_url,
            scopes=["openid", "profile", "email"],
        ),
        claims_mapping=ClaimsMapping(),  # Standard claim names match
    )
