"""Tests for EmailClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from penguin_email.client import EmailClient
from penguin_email.message import EmailMessage
from penguin_email.transports import SendResult


def _make_transport(name: str = "mock", success: bool = True, raises: bool = False) -> MagicMock:
    t = MagicMock()
    t.transport_name = name
    t.health_check = MagicMock(return_value=True)
    t.send = MagicMock()
    if raises:
        t.send.side_effect = RuntimeError(f"{name} failed")
    else:
        t.send.return_value = SendResult(success=success, transport_used=name)
    return t


def _make_message() -> EmailMessage:
    return (
        EmailMessage()
        .to("r@example.com")
        .subject("Hi")
        .html("<p>Hi</p>")
    )


class TestEmailClient:
    def test_invalid_transport_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            EmailClient(transport="not-a-transport")  # type: ignore[arg-type]

    def test_send_calls_primary_transport(self) -> None:
        transport = _make_transport()
        client = EmailClient(transport=transport)
        result = client.send(_make_message())
        assert result.success is True
        transport.send.assert_called_once()

    def test_fallback_on_error_false_raises_when_primary_fails(self) -> None:
        transport = _make_transport(raises=True)
        client = EmailClient(transport=transport, fallback_on_error=False)
        with pytest.raises(RuntimeError, match="mock failed"):
            client.send(_make_message())

    def test_fallback_on_error_true_uses_fallback(self) -> None:
        primary = _make_transport("gmail", raises=True)
        fallback = _make_transport("smtp", success=True)
        client = EmailClient(transport=primary, fallback=fallback, fallback_on_error=True)
        result = client.send(_make_message())
        assert result.transport_used == "smtp"
        assert result.success is True

    def test_fallback_not_called_when_primary_succeeds(self) -> None:
        primary = _make_transport("gmail", success=True)
        fallback = _make_transport("smtp")
        client = EmailClient(transport=primary, fallback=fallback, fallback_on_error=True)
        client.send(_make_message())
        fallback.send.assert_not_called()

    def test_both_transports_fail_returns_failure_result(self) -> None:
        primary = _make_transport("gmail", raises=True)
        fallback = _make_transport("smtp", raises=True)
        client = EmailClient(transport=primary, fallback=fallback, fallback_on_error=True)
        result = client.send(_make_message())
        assert result.success is False
        assert "smtp failed" in result.error

    def test_send_auto_calls_build(self) -> None:
        transport = _make_transport()
        client = EmailClient(transport=transport)
        msg = _make_message()
        assert not msg.is_built
        client.send(msg)
        assert msg.is_built

    def test_template_is_rendered_before_send(self) -> None:
        transport = _make_transport()
        client = EmailClient(transport=transport)
        msg = (
            EmailMessage()
            .to("r@example.com")
            .subject("Welcome!")
            .template("welcome", name="Alice", app_name="App", login_url="http://x")
        )
        client.send(msg)
        assert "<p>" in msg.html_body or "Alice" in msg.html_body

    def test_form_data_rendered_via_form_template(self) -> None:
        transport = _make_transport()
        client = EmailClient(transport=transport)
        msg = (
            EmailMessage()
            .to("r@example.com")
            .subject("Submission")
            .form({"Name": "Alice", "Email": "alice@example.com"})
        )
        client.send(msg)
        assert "Alice" in msg.html_body
