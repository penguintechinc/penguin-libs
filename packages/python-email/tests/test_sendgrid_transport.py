"""Tests for SendGridTransport (mocks requests, no live network calls)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from penguin_email.message import Attachment, EmailMessage
from penguin_email.transports.sendgrid import SendGridTransport


def _make_message(html: str = "<p>Hello</p>") -> EmailMessage:
    msg = EmailMessage().from_addr("sender@x.com").to("recipient@x.com").subject("Subj").html(html)
    msg.build()
    return msg


def _mock_response(status_code: int, headers: dict | None = None, json_body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = json_body if json_body is not None else {}
    response.text = str(json_body or "")
    return response


class TestSendGridTransportInit:
    def test_api_key_read_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "sg_env_key")
        transport = SendGridTransport()
        assert transport._api_key == "sg_env_key"

    def test_api_key_constructor_arg_overrides_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "sg_env_key")
        transport = SendGridTransport(api_key="sg_explicit_key")
        assert transport._api_key == "sg_explicit_key"

    def test_missing_api_key_raises_value_error(self, monkeypatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key"):
            SendGridTransport()

    def test_raises_import_error_when_requests_not_installed(self, monkeypatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "sg_env_key")
        import penguin_email.transports.sendgrid as sg_mod

        original = sg_mod.requests
        sg_mod.requests = None  # type: ignore[assignment]
        try:
            with pytest.raises(ImportError, match="sendgrid"):
                SendGridTransport()
        finally:
            sg_mod.requests = original


class TestSendGridTransportSend:
    def test_send_returns_success_on_202(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        response = _mock_response(202, headers={"X-Message-Id": "msg_abc123"})

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            result = transport.send(_make_message())

        assert result.success is True
        assert result.message_id == "msg_abc123"
        assert result.transport_used == "sendgrid"
        mock_post.assert_called_once()

    def test_send_populates_error_on_non_202(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        response = _mock_response(400, json_body={"errors": [{"message": "bad request"}]})

        with patch("penguin_email.transports.sendgrid.requests.post", return_value=response):
            result = transport.send(_make_message())

        assert result.success is False
        assert "400" in result.error
        assert "bad request" in result.error

    def test_send_returns_failure_on_network_exception(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")

        with patch(
            "penguin_email.transports.sendgrid.requests.post",
            side_effect=ConnectionError("connection refused"),
        ):
            result = transport.send(_make_message())

        assert result.success is False
        assert "connection refused" in result.error

    def test_send_without_sender_returns_failure(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        msg = EmailMessage().to("r@x.com").subject("S").html("<p>hi</p>")
        msg.build()

        result = transport.send(msg)

        assert result.success is False
        assert "from" in result.error.lower()

    def test_send_maps_cc_bcc_and_reply_to(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        msg = (
            EmailMessage()
            .from_addr("s@x.com")
            .to("r@x.com")
            .cc("cc@x.com")
            .bcc("bcc@x.com")
            .reply_to("rt@x.com")
            .subject("Subj")
            .html("<p>hi</p>")
        )
        msg.build()
        response = _mock_response(202, headers={"X-Message-Id": "id1"})

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            transport.send(msg)

        payload = mock_post.call_args.kwargs["json"]
        personalization = payload["personalizations"][0]
        assert personalization["cc"] == [{"email": "cc@x.com"}]
        assert personalization["bcc"] == [{"email": "bcc@x.com"}]
        assert payload["reply_to"] == {"email": "rt@x.com"}

    def test_send_encodes_attachment_as_base64(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        msg = _make_message()
        msg._attachments.append(  # type: ignore[attr-defined]
            Attachment(filename="report.pdf", content_type="application/pdf", data=b"%PDF-1.4")
        )
        response = _mock_response(202, headers={"X-Message-Id": "id2"})

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            transport.send(msg)

        payload = mock_post.call_args.kwargs["json"]
        attachment = payload["attachments"][0]
        assert attachment["filename"] == "report.pdf"
        assert attachment["type"] == "application/pdf"
        assert attachment["disposition"] == "attachment"
        assert "content_id" not in attachment
        assert base64.b64decode(attachment["content"]) == b"%PDF-1.4"

    def test_send_marks_inline_attachment_disposition_and_content_id(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        msg = _make_message()
        msg._attachments.append(  # type: ignore[attr-defined]
            Attachment(
                filename="logo.png",
                content_type="image/png",
                data=b"\x89PNG\r\n\x1a\n",
                cid="logo123",
            )
        )
        response = _mock_response(202, headers={"X-Message-Id": "id3"})

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            transport.send(msg)

        payload = mock_post.call_args.kwargs["json"]
        attachment = payload["attachments"][0]
        assert attachment["disposition"] == "inline"
        assert attachment["content_id"] == "logo123"

    def test_send_includes_bearer_auth_header(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key_12345")
        response = _mock_response(202, headers={"X-Message-Id": "id4"})

        with patch(
            "penguin_email.transports.sendgrid.requests.post", return_value=response
        ) as mock_post:
            transport.send(_make_message())

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sg_test_key_12345"


class TestSendGridTransportHealthCheck:
    def test_health_check_returns_true_on_200(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        response = _mock_response(200)

        with patch("penguin_email.transports.sendgrid.requests.get", return_value=response):
            assert transport.health_check() is True

    def test_health_check_returns_false_on_non_200(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")
        response = _mock_response(401)

        with patch("penguin_email.transports.sendgrid.requests.get", return_value=response):
            assert transport.health_check() is False

    def test_health_check_returns_false_on_exception(self) -> None:
        transport = SendGridTransport(api_key="sg_test_key")

        with patch(
            "penguin_email.transports.sendgrid.requests.get",
            side_effect=OSError("unreachable"),
        ):
            assert transport.health_check() is False


class TestSendGridApiKeyNeverLeaks:
    """The raw API key must never appear in log output or exception messages."""

    def test_key_not_in_send_error_result(self, caplog) -> None:
        secret_key = "SG.super-secret-key-value.dont-leak-me"  # noqa: S105 -- test fixture literal, not a real credential
        transport = SendGridTransport(api_key=secret_key)

        with patch(
            "penguin_email.transports.sendgrid.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            with caplog.at_level("ERROR"):
                result = transport.send(_make_message())

        assert secret_key not in result.error
        assert secret_key not in caplog.text

    def test_key_not_in_error_summary_on_failure_response(self) -> None:
        secret_key = "SG.super-secret-key-value.dont-leak-me"  # noqa: S105 -- test fixture literal, not a real credential
        transport = SendGridTransport(api_key=secret_key)
        response = _mock_response(403, json_body={"errors": [{"message": "forbidden"}]})

        with patch("penguin_email.transports.sendgrid.requests.post", return_value=response):
            result = transport.send(_make_message())

        assert secret_key not in result.error

    def test_key_not_in_repr_or_str(self) -> None:
        secret_key = "SG.super-secret-key-value.dont-leak-me"  # noqa: S105 -- test fixture literal, not a real credential
        transport = SendGridTransport(api_key=secret_key)
        assert secret_key not in repr(transport)
