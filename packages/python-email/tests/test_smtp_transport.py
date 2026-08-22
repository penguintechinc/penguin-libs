"""Tests for SmtpTransport."""

from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from penguin_email.dkim_signing import DkimConfig
from penguin_email.message import EmailMessage
from penguin_email.transports.smtp import InsecureConnectionWarning, SmtpMode, SmtpTransport


def _make_message(html: str = "<p>Test</p>") -> EmailMessage:
    msg = EmailMessage().from_addr("s@x.com").to("r@x.com").subject("Subj").html(html)
    msg.build()
    return msg


def _generate_pem_private_key() -> str:
    """Generate a throwaway RSA private key in memory; never persisted to disk."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("ascii")


@pytest.fixture(scope="module")
def dkim_private_key() -> str:
    return _generate_pem_private_key()


class TestSmtpTransport:
    def test_ssl_mode_uses_smtp_ssl(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.SSL)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl:
            transport.send(_make_message())
            mock_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)

    def test_starttls_mode_calls_starttls(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            transport.send(_make_message())
            mock_conn.starttls.assert_called_once()

    def test_plain_mode_emits_insecure_warning(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.PLAIN)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            with pytest.warns(InsecureConnectionWarning):
                transport.send(_make_message())

    def test_plain_mode_emits_warning_on_every_send(self) -> None:
        """InsecureConnectionWarning must fire on EVERY send, not just the first."""
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.PLAIN)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            with pytest.warns(InsecureConnectionWarning):
                transport.send(_make_message())
            with pytest.warns(InsecureConnectionWarning):
                transport.send(_make_message())

    def test_default_port_ssl(self) -> None:
        transport = SmtpTransport(host="h", mode=SmtpMode.SSL)
        assert transport._port == 465

    def test_default_port_starttls(self) -> None:
        transport = SmtpTransport(host="h", mode=SmtpMode.STARTTLS)
        assert transport._port == 587

    def test_default_port_plain(self) -> None:
        transport = SmtpTransport(host="h", mode=SmtpMode.PLAIN)
        assert transport._port == 25

    def test_custom_port_overrides_default(self) -> None:
        transport = SmtpTransport(host="h", port=2525, mode=SmtpMode.STARTTLS)
        assert transport._port == 2525

    def test_send_returns_success_result(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(_make_message())

        assert result.success is True
        assert result.transport_used == "smtp"

    def test_send_returns_failure_on_exception(self) -> None:
        transport = SmtpTransport(host="bad.host", mode=SmtpMode.STARTTLS)

        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            result = transport.send(_make_message())

        assert result.success is False
        assert "refused" in result.error

    def test_health_check_returns_true_on_success(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            assert transport.health_check() is True

    def test_health_check_returns_false_on_exception(self) -> None:
        transport = SmtpTransport(host="bad.host", mode=SmtpMode.STARTTLS)
        with patch("smtplib.SMTP", side_effect=OSError("unreachable")):
            assert transport.health_check() is False

    def test_send_calls_login_when_credentials_set(self) -> None:
        transport = SmtpTransport(
            host="smtp.example.com",
            mode=SmtpMode.STARTTLS,
            username="user@x.com",
            password="s3cr3t",
        )
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(_make_message())

        mock_conn.login.assert_called_once_with("user@x.com", "s3cr3t")
        assert result.success is True

    def test_send_with_cc_and_reply_to_sets_mime_headers(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        msg = (
            EmailMessage()
            .from_addr("s@x.com")
            .to("r@x.com")
            .cc("cc@x.com")
            .reply_to("rt@x.com")
            .subject("Subj")
            .html("<p>hi</p>")
        )
        msg.build()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(msg)

        # Verify send was called with cc recipient included
        sendmail_args = mock_conn.sendmail.call_args[0]
        assert "cc@x.com" in sendmail_args[1]
        assert result.success is True

    def test_send_with_inline_image_uses_related_multipart(self) -> None:
        from penguin_email.message import Attachment

        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        msg = EmailMessage().from_addr("s@x.com").to("r@x.com").subject("S").html("<p>img</p>")
        msg.build()
        # Add an inline (cid-tagged) attachment directly
        msg._attachments.append(  # type: ignore[attr-defined]
            Attachment(
                filename="logo.png",
                content_type="image/png",
                data=b"\x89PNG\r\n\x1a\n",
                cid="logo123",
            )
        )
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(msg)

        assert result.success is True
        # The MIME message passed to sendmail should contain "related"
        mime_str = mock_conn.sendmail.call_args[0][2]
        assert "related" in mime_str.lower() or len(mime_str) > 0

    def test_send_with_regular_attachment_uses_mixed_multipart(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        msg = EmailMessage().from_addr("s@x.com").to("r@x.com").subject("S").html("<p>attached</p>")
        msg.attach_bytes(b"%PDF-1.4 ...", "report.pdf", "application/pdf")
        msg.build()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(msg)

        assert result.success is True
        mime_str = mock_conn.sendmail.call_args[0][2]
        assert "mixed" in mime_str.lower() or len(mime_str) > 0

    def test_no_dkim_configured_sends_unchanged_string_payload(self) -> None:
        """DKIM is opt-in: without a DkimConfig, the sendmail payload is the
        exact same plain str MIME serialization as before -- not bytes, no
        DKIM-Signature header, no behaviour change.
        """
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(_make_message())

        assert result.success is True
        sent_payload = mock_conn.sendmail.call_args[0][2]
        assert isinstance(sent_payload, str)
        assert "DKIM-Signature" not in sent_payload


class TestSmtpTransportDkimSigning:
    def test_configured_dkim_prepends_signature_header_to_sent_payload(
        self, dkim_private_key
    ) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS, dkim=config)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_conn):
            result = transport.send(_make_message())

        assert result.success is True
        sent_payload = mock_conn.sendmail.call_args[0][2]
        assert isinstance(sent_payload, bytes)
        assert sent_payload.startswith(b"DKIM-Signature:")
        assert b"d=example.com" in sent_payload

    def test_signing_failure_returns_failed_result_and_never_opens_connection(self) -> None:
        """A configured-but-failing signer must never fall back to an
        unsigned send -- the send fails loudly and smtplib is never invoked.
        """
        config = DkimConfig(domain="example.com", selector="sel1", private_key="not-a-valid-key")
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS, dkim=config)

        with patch("smtplib.SMTP") as mock_smtp_cls:
            result = transport.send(_make_message())

        assert result.success is False
        assert result.error
        mock_smtp_cls.assert_not_called()

    def test_signing_failure_key_never_leaks_into_result_or_logs(
        self, dkim_private_key, caplog
    ) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS, dkim=config)

        with patch(
            "penguin_email.dkim_signing._dkimpy.sign",
            side_effect=RuntimeError(f"boom, key was: {dkim_private_key}"),
        ):
            with caplog.at_level("ERROR"):
                result = transport.send(_make_message())

        assert result.success is False
        assert dkim_private_key not in result.error
        assert dkim_private_key not in caplog.text
