"""SendGrid v3 Web API transport."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import SendResult

if TYPE_CHECKING:
    from ..message import EmailMessage

logger = logging.getLogger(__name__)

# Module-level import so unittest.mock.patch can target it by module path.
# Set to None when the [sendgrid] extra is not installed.
try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

_API_BASE = "https://api.sendgrid.com/v3"


class SendGridTransport:
    """Send email via the SendGrid v3 Web API (``POST /v3/mail/send``).

    SendGrid is also reachable through :class:`~penguin_email.transports.smtp.SmtpTransport`
    configured as an SMTP relay (host ``smtp.sendgrid.net``, username ``apikey``,
    password = your SendGrid API key). Prefer *this* REST transport for lower
    latency, structured JSON error responses, and per-message tracking via the
    returned ``X-Message-Id``. Prefer the SMTP relay path when a deployment
    already routes all outbound mail through one SMTP relay for firewall or
    egress-allowlist reasons and adding a second network path is undesirable.

    Requires the ``[sendgrid]`` extra::

        pip install "penguin-email[sendgrid]"
    """

    transport_name: str = "sendgrid"

    def __init__(self, api_key: str | None = None, timeout: int = 30) -> None:
        if requests is None:
            raise ImportError(
                "SendGrid support requires the requests library. "
                "Install with: pip install 'penguin-email[sendgrid]'"
            )

        resolved_key = api_key if api_key is not None else os.environ.get("SENDGRID_API_KEY", "")
        if not resolved_key:
            raise ValueError("SendGrid API key is required: pass api_key= or set SENDGRID_API_KEY")

        self._api_key = resolved_key
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Transport interface
    # ------------------------------------------------------------------

    def send(self, message: EmailMessage) -> SendResult:
        """Build a SendGrid JSON payload and POST it to ``/v3/mail/send``."""
        try:
            payload = self._build_payload(message)
            response = requests.post(
                f"{_API_BASE}/mail/send",
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
            if response.status_code == 202:
                return SendResult(
                    success=True,
                    transport_used=self.transport_name,
                    message_id=response.headers.get("X-Message-Id", ""),
                )
            return SendResult(
                success=False,
                transport_used=self.transport_name,
                error=self._error_summary(response),
            )
        except Exception as exc:
            # str(exc) may echo request context (URL, body) but never the
            # Authorization header, so the API key is never logged here.
            logger.error("SendGridTransport send error: %s", exc)
            return SendResult(
                success=False,
                transport_used=self.transport_name,
                error=str(exc),
            )

    def health_check(self) -> bool:
        """Verify the API key is valid via a cheap authenticated ``GET /v3/scopes``."""
        try:
            response = requests.get(
                f"{_API_BASE}/scopes",
                headers=self._headers(),
                timeout=self._timeout,
            )
            return response.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, message: EmailMessage) -> dict[str, Any]:
        """Map an :class:`EmailMessage` onto the SendGrid v3 mail/send schema."""
        if not message.sender:
            raise ValueError("A 'from' address is required to send via SendGrid")

        personalization: dict[str, Any] = {
            "to": [{"email": addr} for addr in message.recipients],
        }
        if message.cc_recipients:
            personalization["cc"] = [{"email": addr} for addr in message.cc_recipients]
        if message.bcc_recipients:
            personalization["bcc"] = [{"email": addr} for addr in message.bcc_recipients]

        payload: dict[str, Any] = {
            "personalizations": [personalization],
            "from": {"email": message.sender},
            "subject": message.subject_line,
            "content": self._build_content(message),
        }
        if message.reply_to_addr:
            payload["reply_to"] = {"email": message.reply_to_addr}

        attachments = self._build_attachments(message)
        if attachments:
            payload["attachments"] = attachments

        return payload

    def _build_content(self, message: EmailMessage) -> list[dict[str, str]]:
        """Build the ``content`` array (text/plain first, then text/html)."""
        plain = message.text_body or ""
        if not plain and message.html_body:
            from ..templates.engine import TemplateRenderer

            plain = TemplateRenderer().strip_tags(message.html_body)

        content: list[dict[str, str]] = []
        if plain:
            content.append({"type": "text/plain", "value": plain})
        if message.html_body:
            content.append({"type": "text/html", "value": message.html_body})
        return content

    def _build_attachments(self, message: EmailMessage) -> list[dict[str, str]]:
        """Base64-encode every attachment; inline (cid) attachments get ``content_id``."""
        attachments: list[dict[str, str]] = []
        for att in message.attachments:
            data = att.data or Path(att.path or "").read_bytes()
            entry: dict[str, str] = {
                "content": base64.b64encode(data).decode("ascii"),
                "type": att.content_type,
                "filename": att.filename,
                "disposition": "inline" if att.cid else "attachment",
            }
            if att.cid:
                entry["content_id"] = att.cid
            attachments.append(entry)
        return attachments

    def _error_summary(self, response: Any) -> str:
        """Summarize a non-202 response body without ever including request headers."""
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return f"SendGrid API returned {response.status_code}: {body}"
