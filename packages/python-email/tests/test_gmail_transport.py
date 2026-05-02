"""Tests for GmailTransport (mocks googleapiclient)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from penguin_email.message import EmailMessage


def _make_message(with_attachment: bool = False, with_inline: bool = False) -> EmailMessage:
    msg = (
        EmailMessage()
        .from_addr("sender@gmail.com")
        .to("recipient@example.com")
        .subject("Test")
        .html("<p>Hello</p>")
    )
    if with_attachment:
        msg.attach_bytes(b"filedata", "report.pdf", "application/pdf")
    if with_inline:
        msg.inline_image.__doc__  # just reference it to avoid unused import
        msg._attachments.append(  # type: ignore[attr-defined]
            __import__("penguin_email.message", fromlist=["Attachment"]).Attachment(
                filename="logo.png",
                content_type="image/png",
                data=b"\x89PNG",
                cid="logo",
            )
        )
    msg.build()
    return msg


@pytest.fixture()
def mock_gmail_service() -> MagicMock:
    service = MagicMock()
    send_result = {"id": "msg_abc123"}
    service.users().messages().send().execute.return_value = send_result
    service.users().getProfile().execute.return_value = {"emailAddress": "sender@gmail.com"}
    return service


class TestGmailTransportFromEnv:
    def test_from_env_reads_correct_env_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("GMAIL_CLIENT_ID", "client_id_val")
        monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client_secret_val")
        monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh_token_val")
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "sender@gmail.com")

        mock_creds = MagicMock()
        mock_service = MagicMock()

        with (
            patch("penguin_email.transports.gmail.Credentials", return_value=mock_creds),
            patch("penguin_email.transports.gmail.build", return_value=mock_service),
        ):
            from penguin_email.transports.gmail import GmailTransport

            transport = GmailTransport.from_env()

        assert transport._sender_email == "sender@gmail.com"
        assert transport._service is mock_service


class TestGmailTransportSend:
    def test_send_calls_gmail_api(self, mock_gmail_service) -> None:
        from penguin_email.transports.gmail import GmailTransport

        transport = GmailTransport(service=mock_gmail_service, sender_email="s@g.com")
        result = transport.send(_make_message())

        assert result.success is True
        assert result.message_id == "msg_abc123"
        assert result.transport_used == "gmail"
        mock_gmail_service.users().messages().send.assert_called()

    def test_send_encodes_raw_as_base64url(self, mock_gmail_service) -> None:
        from penguin_email.transports.gmail import GmailTransport

        transport = GmailTransport(service=mock_gmail_service, sender_email="s@g.com")
        transport.send(_make_message())

        call_kwargs = mock_gmail_service.users().messages().send.call_args
        body = call_kwargs[1]["body"] if call_kwargs[1] else call_kwargs[0][1]
        raw = body["raw"]
        # Should be decodable as base64url
        decoded = base64.urlsafe_b64decode(raw + "==")
        assert len(decoded) > 0

    def test_send_includes_attachment_in_mime(self, mock_gmail_service) -> None:
        from penguin_email.transports.gmail import GmailTransport

        transport = GmailTransport(service=mock_gmail_service, sender_email="s@g.com")
        msg = _make_message(with_attachment=True)
        result = transport.send(msg)
        assert result.success is True

    def test_send_returns_failure_on_api_error(self) -> None:
        from penguin_email.transports.gmail import GmailTransport

        service = MagicMock()
        service.users().messages().send().execute.side_effect = Exception("API error")
        transport = GmailTransport(service=service, sender_email="s@g.com")
        result = transport.send(_make_message())
        assert result.success is False
        assert "API error" in result.error

    def test_health_check_returns_true(self, mock_gmail_service) -> None:
        from penguin_email.transports.gmail import GmailTransport

        transport = GmailTransport(service=mock_gmail_service, sender_email="s@g.com")
        assert transport.health_check() is True

    def test_health_check_returns_false_on_exception(self) -> None:
        from penguin_email.transports.gmail import GmailTransport

        service = MagicMock()
        service.users().getProfile().execute.side_effect = Exception("no auth")
        transport = GmailTransport(service=service, sender_email="s@g.com")
        assert transport.health_check() is False


class TestGmailTransportFromFiles:
    def test_from_files_happy_path(self, tmp_path) -> None:
        """from_files() builds a transport from credentials + token JSON files."""
        import json

        token_data = {
            "token": "access_tok",
            "refresh_token": "ref_tok",
            "client_id": "cid",
            "client_secret": "csec",
            "scopes": ["https://www.googleapis.com/auth/gmail.send"],
            "email": "sender@gmail.com",
        }
        cred_data = {"installed": {"client_email": "sender@gmail.com"}}

        token_file = tmp_path / "token.json"
        cred_file = tmp_path / "creds.json"
        token_file.write_text(json.dumps(token_data))
        cred_file.write_text(json.dumps(cred_data))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.refresh_token = None
        mock_service = MagicMock()

        with (
            patch("penguin_email.transports.gmail.Credentials") as mock_creds_cls,
            patch("penguin_email.transports.gmail.build", return_value=mock_service),
        ):
            mock_creds_cls.from_authorized_user_info.return_value = mock_creds
            from penguin_email.transports.gmail import GmailTransport

            transport = GmailTransport.from_files(str(cred_file), str(token_file))

        assert transport._service is mock_service
        mock_creds_cls.from_authorized_user_info.assert_called_once_with(token_data)

    def test_from_files_refreshes_expired_token(self, tmp_path) -> None:
        """from_files() calls creds.refresh() when the token is expired."""
        import json

        token_data = {"token": "old", "refresh_token": "rt", "client_id": "c", "client_secret": "s"}
        cred_data = {"installed": {}}
        token_file = tmp_path / "token.json"
        cred_file = tmp_path / "creds.json"
        token_file.write_text(json.dumps(token_data))
        cred_file.write_text(json.dumps(cred_data))

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "rt"
        mock_creds.to_json.return_value = json.dumps({"token": "new_tok"})
        mock_service = MagicMock()

        with (
            patch("penguin_email.transports.gmail.Credentials") as mock_creds_cls,
            patch("penguin_email.transports.gmail.build", return_value=mock_service),
            patch("google.auth.transport.requests.Request"),
        ):
            mock_creds_cls.from_authorized_user_info.return_value = mock_creds
            from penguin_email.transports.gmail import GmailTransport

            GmailTransport.from_files(str(cred_file), str(token_file))

        mock_creds.refresh.assert_called_once()


class TestGmailTransportFromConfig:
    def test_from_config_builds_transport(self) -> None:
        config = {
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "reftok",
            "sender_email": "bot@gmail.com",
        }
        mock_creds = MagicMock()
        mock_service = MagicMock()

        with (
            patch("penguin_email.transports.gmail.Credentials", return_value=mock_creds),
            patch("penguin_email.transports.gmail.build", return_value=mock_service),
        ):
            from penguin_email.transports.gmail import GmailTransport

            transport = GmailTransport.from_config(config)

        assert transport._service is mock_service
        assert transport._sender_email == "bot@gmail.com"

    def test_from_config_raises_when_gmail_not_installed(self) -> None:
        import penguin_email.transports.gmail as gm_mod

        original = gm_mod.Credentials
        gm_mod.Credentials = None  # type: ignore[assignment]
        try:
            from penguin_email.transports.gmail import GmailTransport

            with pytest.raises(ImportError, match="gmail"):
                GmailTransport.from_config(
                    {"client_id": "x", "client_secret": "x", "refresh_token": "x", "sender_email": "x"}
                )
        finally:
            gm_mod.Credentials = original
