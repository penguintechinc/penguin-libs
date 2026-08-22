"""Gmail OAuth2 flow and token refresh helpers."""

from __future__ import annotations

from typing import Any, Protocol

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class RefreshableCredentials(Protocol):
    """Structural type for the google-auth credential object we refresh.

    The google-auth libraries ship no type stubs, so this Protocol pins the
    one method :func:`refresh_credentials` actually calls rather than falling
    back to an untyped ``object``.
    """

    def refresh(self, request: Any) -> None:
        """Exchange the stored refresh token for a fresh access token."""
        ...


# Module-level imports so that unittest.mock.patch can target them.
# Both are None when the [gmail] extra is not installed.
try:
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    InstalledAppFlow = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]


def run_oauth_flow(
    credentials_path: str,
    token_path: str,
    scopes: list[str] | None = None,
) -> None:
    """Run the Google OAuth2 installed-app flow and save the token.

    Opens a browser window for the user to grant permission.  The resulting
    token is written to *token_path* for later use by
    :class:`~penguin_email.transports.gmail.GmailTransport`.

    Parameters
    ----------
    credentials_path:
        Path to the ``credentials.json`` file downloaded from the Google
        Cloud Console (OAuth 2.0 Client IDs).
    token_path:
        Path where the resulting ``token.json`` will be written (or
        overwritten on refresh).
    scopes:
        OAuth2 scopes to request.  Defaults to
        ``["https://www.googleapis.com/auth/gmail.send"]``.
    """
    if InstalledAppFlow is None:
        raise ImportError(
            "Gmail support requires 'google-auth-oauthlib'. "
            "Install with: pip install 'penguin-email[gmail]'"
        )

    requested_scopes = scopes or _SCOPES
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, requested_scopes)
    creds = flow.run_local_server(port=0)

    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {token_path}")


def refresh_credentials(creds: RefreshableCredentials) -> RefreshableCredentials:
    """Refresh an expired Google OAuth2 credential object.

    Calls ``creds.refresh(Request())`` using the stored refresh token.
    Returns the same credential object (mutated in place) for convenience.

    Parameters
    ----------
    creds:
        A :class:`google.oauth2.credentials.Credentials` instance.
    """
    if Request is None:
        raise ImportError(
            "Gmail support requires 'google-auth'. Install with: pip install 'penguin-email[gmail]'"
        )

    creds.refresh(Request())
    return creds
