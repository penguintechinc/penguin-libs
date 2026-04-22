"""Gmail REST API transport."""

from __future__ import annotations

import base64
import logging
import os
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import SendResult

if TYPE_CHECKING:
    from ..message import EmailMessage

logger = logging.getLogger(__name__)

# Module-level imports so unittest.mock.patch can target them by module path.
# Set to None when the [gmail] extra is not installed.
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None  # type: ignore[assignment, misc]
    build = None  # type: ignore[assignment, misc]


class GmailTransport:
    """Send email via the Gmail REST API (``gmail.users.messages.send``).

    Requires the ``[gmail]`` extra::

        pip install "penguin-email[gmail]"

    Token refresh is handled automatically by ``google-auth``.  When using
    :meth:`from_files`, the refreshed token is written back to *token_path*.
    When using :meth:`from_env`, the refreshed token is kept in memory only
    (the caller's environment is not mutated).
    """

    transport_name: str = "gmail"

    def __init__(self, service: Any, sender_email: str) -> None:
        self._service = service
        self._sender_email = sender_email

    # ------------------------------------------------------------------
    # Factory constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "GmailTransport":
        """Build a transport from environment variables.

        Required env vars::

            GMAIL_CLIENT_ID
            GMAIL_CLIENT_SECRET
            GMAIL_REFRESH_TOKEN
            GMAIL_SENDER_EMAIL
        """
        if Credentials is None or build is None:
            raise ImportError(
                "Gmail support requires google-auth extras. "
                "Install with: pip install 'penguin-email[gmail]'"
            )

        client_id = os.environ["GMAIL_CLIENT_ID"]
        client_secret = os.environ["GMAIL_CLIENT_SECRET"]
        refresh_token = os.environ["GMAIL_REFRESH_TOKEN"]
        sender_email = os.environ["GMAIL_SENDER_EMAIL"]

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        service = build("gmail", "v1", credentials=creds)
        return cls(service=service, sender_email=sender_email)

    @classmethod
    def from_files(cls, credentials_path: str, token_path: str) -> "GmailTransport":
        """Build a transport from ``credentials.json`` and ``token.json``.

        Refreshes the token if expired and writes the updated token back to
        *token_path*.
        """
        import json

        if Credentials is None or build is None:
            raise ImportError(
                "Gmail support requires google-auth extras. "
                "Install with: pip install 'penguin-email[gmail]'"
            )
        from google.auth.transport.requests import Request

        with open(token_path) as f:
            token_data = json.load(f)

        creds = Credentials.from_authorized_user_info(token_data)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        with open(credentials_path) as f:
            cred_data = json.load(f)

        sender_email = cred_data.get("installed", cred_data.get("web", {})).get(
            "client_email", ""
        )
        # Fallback: use token subject/email if available
        if not sender_email and hasattr(creds, "token") and creds.token:
            sender_email = token_data.get("email", "")

        service = build("gmail", "v1", credentials=creds)
        return cls(service=service, sender_email=sender_email)

    @classmethod
    def from_config(cls, config: dict[str, str]) -> "GmailTransport":
        """Build a transport from a plain dict (e.g. from Vault/secrets manager).

        Expected keys: ``client_id``, ``client_secret``, ``refresh_token``,
        ``sender_email``.
        """
        if Credentials is None or build is None:
            raise ImportError(
                "Gmail support requires google-auth extras. "
                "Install with: pip install 'penguin-email[gmail]'"
            )

        creds = Credentials(
            token=None,
            refresh_token=config["refresh_token"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
        )
        service = build("gmail", "v1", credentials=creds)
        return cls(service=service, sender_email=config["sender_email"])

    # ------------------------------------------------------------------
    # Transport interface
    # ------------------------------------------------------------------

    def send(self, message: "EmailMessage") -> SendResult:
        """Build a MIME message and POST it to the Gmail API."""
        try:
            mime = self._build_mime(message)
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            result = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
            return SendResult(
                success=True,
                transport_used=self.transport_name,
                message_id=result.get("id", ""),
            )
        except Exception as exc:
            logger.error("GmailTransport send error: %s", exc)
            return SendResult(
                success=False,
                transport_used=self.transport_name,
                error=str(exc),
            )

    def health_check(self) -> bool:
        """Verify credentials are valid by calling ``gmail.users.getProfile``."""
        try:
            self._service.users().getProfile(userId="me").execute()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_mime(self, message: "EmailMessage") -> MIMEMultipart:
        """Construct the MIME message tree."""
        inline = [a for a in message.attachments if a.cid is not None]
        regular = [a for a in message.attachments if a.cid is None]

        if inline:
            outer = MIMEMultipart("related")
            alt = MIMEMultipart("alternative")
        else:
            outer = MIMEMultipart("mixed") if regular else MIMEMultipart("alternative")
            alt = outer if not regular else MIMEMultipart("alternative")

        # Headers
        if message.sender:
            outer["From"] = message.sender
        outer["To"] = ", ".join(message.recipients)
        if message.cc_recipients:
            outer["Cc"] = ", ".join(message.cc_recipients)
        if message.reply_to_addr:
            outer["Reply-To"] = message.reply_to_addr
        outer["Subject"] = message.subject_line

        # Plain text
        plain = message.text_body or ""
        if not plain and message.html_body:
            from ..templates.engine import TemplateRenderer

            plain = TemplateRenderer().strip_tags(message.html_body)
        if plain:
            alt.attach(MIMEText(plain, "plain", "utf-8"))

        # HTML
        if message.html_body:
            alt.attach(MIMEText(message.html_body, "html", "utf-8"))

        if regular and alt is not outer:
            outer.attach(alt)

        if inline:
            if alt is not outer:
                pass  # alt already attached to outer above
            else:
                outer.attach(alt)
            for att in inline:
                data = att.data or Path(att.path or "").read_bytes()
                img = MIMEImage(data, _subtype=att.content_type.split("/")[-1])
                img.add_header("Content-ID", f"<{att.cid}>")
                img.add_header("Content-Disposition", "inline", filename=att.filename)
                outer.attach(img)

        # Regular attachments
        for att in regular:
            data = att.data or Path(att.path or "").read_bytes()
            part = MIMEApplication(data)
            part.add_header(
                "Content-Disposition", "attachment", filename=att.filename
            )
            outer.attach(part)

        return outer
