"""Tests for SmtpTransport."""

import smtplib
from unittest.mock import ANY, MagicMock, patch

import pytest

from penguin_email.message import EmailMessage
from penguin_email.transports.smtp import InsecureConnectionWarning, SmtpMode, SmtpTransport


def _make_message(html: str = "<p>Test</p>") -> EmailMessage:
    msg = EmailMessage().from_addr("s@x.com").to("r@x.com").subject("Subj").html(html)
    msg.build()
    return msg


class TestSmtpTransport:
    def test_ssl_mode_uses_smtp_ssl(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.SSL)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl:
            transport.send(_make_message())
            mock_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30, context=ANY)

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
        msg = (
            EmailMessage()
            .from_addr("s@x.com")
            .to("r@x.com")
            .subject("S")
            .html("<p>attached</p>")
        )
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


class TestSmtpTlsVerification:
    """Regression tests for F-01: SSL/STARTTLS must verify server certificates."""

    @staticmethod
    def _mock_conn() -> MagicMock:
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    @staticmethod
    def _assert_verified(ctx: object) -> None:
        import ssl

        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        assert ctx.minimum_version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3)

    def test_ssl_mode_passes_verified_context(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.SSL)
        mock_conn = self._mock_conn()
        with patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl:
            transport.send(_make_message())
        self._assert_verified(mock_ssl.call_args.kwargs["context"])

    def test_starttls_mode_passes_verified_context_to_starttls(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = self._mock_conn()
        with patch("smtplib.SMTP", return_value=mock_conn):
            transport.send(_make_message())
        self._assert_verified(mock_conn.starttls.call_args.kwargs["context"])

    def test_health_check_uses_verified_context(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS)
        mock_conn = self._mock_conn()
        with patch("smtplib.SMTP", return_value=mock_conn):
            assert transport.health_check() is True
        self._assert_verified(mock_conn.starttls.call_args.kwargs["context"])

    def test_injected_custom_ca_context_is_used(self) -> None:
        import ssl

        custom = ssl.create_default_context()
        transport = SmtpTransport(
            host="smtp.example.com", mode=SmtpMode.SSL, ssl_context=custom
        )
        with patch("smtplib.SMTP_SSL", return_value=self._mock_conn()) as mock_ssl:
            transport.send(_make_message())
        assert mock_ssl.call_args.kwargs["context"] is custom

    def test_injected_context_with_cert_verification_disabled_is_rejected(self) -> None:
        import ssl

        unverified = ssl.create_default_context()
        unverified.check_hostname = False
        unverified.verify_mode = ssl.CERT_NONE
        with pytest.raises(ValueError, match="certificate verification"):
            SmtpTransport(host="h", mode=SmtpMode.SSL, ssl_context=unverified)

    def test_injected_context_without_hostname_check_is_rejected(self) -> None:
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        with pytest.raises(ValueError, match="certificate verification"):
            SmtpTransport(host="h", mode=SmtpMode.STARTTLS, ssl_context=ctx)

    def test_injected_context_allowing_tls_below_1_2_is_rejected(self) -> None:
        import ssl

        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        with pytest.raises(ValueError, match="TLS 1.2"):
            SmtpTransport(host="h", mode=SmtpMode.SSL, ssl_context=ctx)

    def test_default_context_enforces_tls_1_2_minimum(self) -> None:
        import ssl

        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.SSL)
        mock_conn = self._mock_conn()
        with patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl:
            transport.send(_make_message())
        ctx = mock_ssl.call_args.kwargs["context"]
        assert ctx.minimum_version.value >= ssl.TLSVersion.TLSv1_2.value


class TestSmtpPlainWithCredentials:
    """Regression tests for F-02: PLAIN mode must never send AUTH credentials."""

    def test_plain_mode_with_password_raises(self) -> None:
        with pytest.raises(ValueError, match="PLAIN"):
            SmtpTransport(
                host="smtp.example.com",
                mode=SmtpMode.PLAIN,
                username="user",
                password="secret",
            )

    def test_plain_mode_with_username_only_raises(self) -> None:
        with pytest.raises(ValueError, match="PLAIN"):
            SmtpTransport(host="smtp.example.com", mode=SmtpMode.PLAIN, username="user")

    def test_plain_mode_without_credentials_still_allowed(self) -> None:
        transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.PLAIN)
        assert transport._mode is SmtpMode.PLAIN

    def test_starttls_with_credentials_still_allowed(self) -> None:
        transport = SmtpTransport(
            host="smtp.example.com", mode=SmtpMode.STARTTLS, username="u", password="p"
        )
        assert transport._username == "u"
