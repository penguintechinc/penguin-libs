"""Tests for per-sender Signature blocks and their application in EmailClient.

Signature application lives entirely in ``EmailClient._apply_signature`` (see
client.py) — never in a transport — so these tests mostly drive the client
directly with a mocked transport, plus one test per real transport (SMTP,
Gmail, SendGrid) proving each one receives the already-signed body without
any transport-specific signature code.
"""

from __future__ import annotations

import base64
import email
from unittest.mock import MagicMock, patch

from penguin_email.client import EmailClient
from penguin_email.message import EmailMessage
from penguin_email.signature import Signature
from penguin_email.transports import SendResult
from penguin_email.transports.gmail import GmailTransport
from penguin_email.transports.sendgrid import SendGridTransport
from penguin_email.transports.smtp import SmtpMode, SmtpTransport


def _make_transport(name: str = "mock") -> MagicMock:
    t = MagicMock()
    t.transport_name = name
    t.health_check = MagicMock(return_value=True)
    t.send = MagicMock(return_value=SendResult(success=True, transport_used=name))
    return t


def _make_message() -> EmailMessage:
    return EmailMessage().to("r@example.com").subject("Hi").html("<p>Body</p>")


def _decoded_text_parts(mime_str: str) -> list[str]:
    """Decode every text/* MIME part (handles base64/quoted-printable transfer
    encoding) so signature content can be searched for regardless of how the
    email library chose to encode it."""
    parsed = email.message_from_string(mime_str)
    parts: list[str] = []
    for part in parsed.walk():
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        parts.append(payload.decode(charset, errors="replace"))
    return parts


class TestSignatureDataclass:
    def test_defaults(self) -> None:
        sig = Signature(html="<p>Hi</p>")
        assert sig.text == ""
        assert sig.variables == {}

    def test_is_slotted(self) -> None:
        sig = Signature(html="<p>Hi</p>")
        assert not hasattr(sig, "__dict__")


class TestSignatureApplication:
    def test_no_signature_leaves_bodies_unchanged(self) -> None:
        transport = _make_transport()
        client = EmailClient(transport=transport)
        msg = _make_message()
        client.send(msg)
        assert msg.html_body == "<p>Body</p>"
        # Untouched — the per-transport strip_tags fallback still owns this.
        assert msg.text_body == ""

    def test_html_only_message_gets_html_and_text_signature(self) -> None:
        transport = _make_transport()
        sig = Signature(html="<p>-- <br>Jane</p>", text="-- \nJane")
        client = EmailClient(transport=transport, default_signature=sig)
        msg = _make_message()
        client.send(msg)
        assert msg.html_body == "<p>Body</p><p>-- <br>Jane</p>"
        assert msg.text_body == "Body\n\n-- \nJane"

    def test_explicit_text_message_keeps_explicit_text_and_appends_signature(self) -> None:
        transport = _make_transport()
        sig = Signature(html="<p>Sig</p>", text="Sig")
        client = EmailClient(transport=transport, default_signature=sig)
        msg = _make_message().text("Explicit text body")
        client.send(msg)
        assert msg.text_body == "Explicit text body\n\nSig"
        assert msg.html_body == "<p>Body</p><p>Sig</p>"

    def test_per_message_signature_overrides_client_default(self) -> None:
        transport = _make_transport()
        client_sig = Signature(html="<p>Client</p>", text="Client")
        msg_sig = Signature(html="<p>Message</p>", text="Message")
        client = EmailClient(transport=transport, default_signature=client_sig)
        msg = _make_message().signature(msg_sig)
        client.send(msg)
        assert "Message" in msg.html_body
        assert "Client" not in msg.html_body
        assert msg.text_body.endswith("Message")
        assert "Client" not in msg.text_body

    def test_client_default_used_when_message_has_no_override(self) -> None:
        transport = _make_transport()
        client_sig = Signature(html="<p>Client</p>", text="Client")
        client = EmailClient(transport=transport, default_signature=client_sig)
        msg = _make_message()
        client.send(msg)
        assert "Client" in msg.html_body

    def test_signature_without_text_derives_from_html_via_strip_tags(self) -> None:
        transport = _make_transport()
        sig = Signature(html="<p>Jane <b>Doe</b></p>")
        client = EmailClient(transport=transport, default_signature=sig)
        msg = _make_message()
        client.send(msg)
        sig_part = msg.text_body.split("\n\n")[-1]
        assert "Jane" in sig_part
        assert "Doe" in sig_part
        assert "<" not in sig_part

    def test_distinct_signature_text_not_derived_from_merged_html(self) -> None:
        """A distinct signature.text must survive verbatim, not get re-derived
        by stripping tags from body_html + signature_html merged together."""
        transport = _make_transport()
        sig = Signature(html="<table><tr><td>Jane</td></tr></table>", text="Jane Doe, CEO")
        client = EmailClient(transport=transport, default_signature=sig)
        msg = _make_message()
        client.send(msg)
        assert msg.text_body == "Body\n\nJane Doe, CEO"

    def test_jinja_variables_render_in_signature_html_and_text(self) -> None:
        transport = _make_transport()
        sig = Signature(
            html="<p>Signed, {{ sender_name }}</p>",
            text="Signed, {{ sender_name }}",
            variables={"sender_name": "Alice & Bob"},
        )
        client = EmailClient(transport=transport, default_signature=sig)
        msg = _make_message()
        client.send(msg)
        # HTML rendering escapes the substituted variable (autoescape=True).
        assert "Alice &amp; Bob" in msg.html_body
        # Text rendering does not HTML-escape (autoescape=False).
        assert "Alice & Bob" in msg.text_body
        assert "&amp;" not in msg.text_body


class TestSignatureAcrossTransports:
    """Same Signature, three real transports — none contain signature code."""

    def _sig(self) -> Signature:
        return Signature(html="<p>-- Sig HTML</p>", text="-- Sig Text")

    def test_smtp_transport_receives_signed_body(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        client = EmailClient(transport=transport, default_signature=self._sig())
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = client.send(
                EmailMessage().from_addr("s@x.com").to("r@x.com").subject("Hi").html("<p>Body</p>")
            )

        assert result.success is True
        mime_str = mock_conn.sendmail.call_args[0][2]
        parts = _decoded_text_parts(mime_str)
        assert any("Sig HTML" in p for p in parts)
        assert any("Sig Text" in p for p in parts)

    def test_gmail_transport_receives_signed_body(self) -> None:
        service = MagicMock()
        service.users().messages().send().execute.return_value = {"id": "abc123"}
        transport = GmailTransport(service=service, sender_email="s@gmail.com")
        client = EmailClient(transport=transport, default_signature=self._sig())

        result = client.send(
            EmailMessage().from_addr("s@x.com").to("r@x.com").subject("Hi").html("<p>Body</p>")
        )

        assert result.success is True
        call_args = service.users().messages().send.call_args
        raw = call_args.kwargs["body"]["raw"]
        mime_str = base64.urlsafe_b64decode(raw + "==").decode(errors="replace")
        parts = _decoded_text_parts(mime_str)
        assert any("Sig HTML" in p for p in parts)
        assert any("Sig Text" in p for p in parts)

    def test_sendgrid_transport_receives_signed_body(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        client = EmailClient(transport=transport, default_signature=self._sig())
        response = MagicMock()
        response.status_code = 202
        response.headers = {"X-Message-Id": "mid_123"}

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            result = client.send(
                EmailMessage().from_addr("s@x.com").to("r@x.com").subject("Hi").html("<p>Body</p>")
            )

        assert result.success is True
        payload = mock_post.call_args.kwargs["json"]
        content = {c["type"]: c["value"] for c in payload["content"]}
        assert "Sig HTML" in content["text/html"]
        assert "Sig Text" in content["text/plain"]
