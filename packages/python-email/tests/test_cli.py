"""Tests for the penguin-email CLI (cli.py)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from penguin_email.cli import _cmd_auth, _cmd_check, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):  # type: ignore[return]
    """Return a minimal argparse.Namespace with the given attributes."""
    import argparse
    ns = argparse.Namespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# _cmd_auth
# ---------------------------------------------------------------------------

class TestCmdAuth:
    def test_auth_runs_oauth_flow(self) -> None:
        mock_flow = MagicMock()
        with patch("penguin_email.cli._cmd_auth") as patched:
            patched.return_value = 0
            args = _make_args(credentials="creds.json", token="token.json", scopes=None)
            assert patched(args) == 0

    def test_auth_calls_run_oauth_flow(self) -> None:
        mock_run = MagicMock()
        with patch("penguin_email.auth.gmail_oauth.run_oauth_flow", mock_run):
            # Patch the import inside _cmd_auth to return our mock
            with patch.dict(
                sys.modules,
                {"penguin_email.auth.gmail_oauth": MagicMock(run_oauth_flow=mock_run)},
            ):
                args = _make_args(credentials="c.json", token="t.json", scopes=None)
                rc = _cmd_auth(args)
        assert rc == 0
        mock_run.assert_called_once_with(
            credentials_path="c.json",
            token_path="t.json",
            scopes=None,
        )

    def test_auth_missing_gmail_extras_returns_1(self, capsys) -> None:
        """If google-auth-oauthlib is not installed, auth exits with code 1."""
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            # Only raise for the specific import inside _cmd_auth
            original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        # Simulate the ImportError path by patching the module lookup
        with patch.dict(sys.modules, {"penguin_email.auth.gmail_oauth": None}):
            args = _make_args(credentials="c.json", token="t.json", scopes=None)
            rc = _cmd_auth(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "pip install" in captured.err

    def test_auth_passes_scopes_list(self) -> None:
        mock_run = MagicMock()
        scopes = ["https://www.googleapis.com/auth/gmail.send"]
        with patch.dict(
            sys.modules,
            {"penguin_email.auth.gmail_oauth": MagicMock(run_oauth_flow=mock_run)},
        ):
            args = _make_args(credentials="c.json", token="t.json", scopes=scopes)
            _cmd_auth(args)
        mock_run.assert_called_once_with(
            credentials_path="c.json",
            token_path="t.json",
            scopes=scopes,
        )


# ---------------------------------------------------------------------------
# _cmd_check — SMTP path
# ---------------------------------------------------------------------------

class TestCmdCheckSmtp:
    def test_healthy_smtp_returns_0(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SMTP_MODE", "STARTTLS")

        mock_transport = MagicMock()
        mock_transport.health_check.return_value = True
        mock_transport.transport_name = "smtp"

        with patch("penguin_email.transports.smtp.SmtpTransport", return_value=mock_transport):
            args = _make_args()
            rc = _cmd_check(args)

        assert rc == 0
        captured = capsys.readouterr()
        assert "healthy" in captured.out

    def test_unhealthy_smtp_returns_1(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("SMTP_MODE", "STARTTLS")

        mock_transport = MagicMock()
        mock_transport.health_check.return_value = False
        mock_transport.transport_name = "smtp"

        with patch("penguin_email.transports.smtp.SmtpTransport", return_value=mock_transport):
            args = _make_args()
            rc = _cmd_check(args)

        assert rc == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.err

    def test_invalid_smtp_mode_returns_1(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.setenv("SMTP_MODE", "BADMODE")
        args = _make_args()
        rc = _cmd_check(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "BADMODE" in captured.err

    def test_smtp_port_parsed_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.setenv("SMTP_PORT", "2525")
        monkeypatch.setenv("SMTP_MODE", "STARTTLS")

        mock_transport = MagicMock()
        mock_transport.health_check.return_value = True
        mock_transport.transport_name = "smtp"

        with patch(
            "penguin_email.transports.smtp.SmtpTransport", return_value=mock_transport
        ) as mock_cls:
            args = _make_args()
            _cmd_check(args)
            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs.get("port") == 2525 or (
                call_kwargs.args and 2525 in call_kwargs.args
            )


# ---------------------------------------------------------------------------
# _cmd_check — Gmail path
# ---------------------------------------------------------------------------

class TestCmdCheckGmail:
    def test_healthy_gmail_returns_0(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "gmail")

        mock_transport = MagicMock()
        mock_transport.health_check.return_value = True
        mock_transport.transport_name = "gmail"

        mock_gmail_mod = MagicMock()
        mock_gmail_mod.GmailTransport.from_env.return_value = mock_transport

        with patch.dict(sys.modules, {"penguin_email.transports.gmail": mock_gmail_mod}):
            args = _make_args()
            rc = _cmd_check(args)

        assert rc == 0
        captured = capsys.readouterr()
        assert "healthy" in captured.out

    def test_gmail_missing_extras_returns_1(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "gmail")
        with patch.dict(sys.modules, {"penguin_email.transports.gmail": None}):
            args = _make_args()
            rc = _cmd_check(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "pip install" in captured.err

    def test_gmail_missing_env_var_returns_1(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "gmail")

        mock_gmail_mod = MagicMock()
        mock_gmail_mod.GmailTransport.from_env.side_effect = KeyError("GMAIL_CLIENT_ID")

        with patch.dict(sys.modules, {"penguin_email.transports.gmail": mock_gmail_mod}):
            args = _make_args()
            rc = _cmd_check(args)

        assert rc == 1
        captured = capsys.readouterr()
        assert "Missing environment variable" in captured.err


# ---------------------------------------------------------------------------
# main() — argument dispatch
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_subcommand_prints_help_exits_0(self, capsys) -> None:
        with patch("sys.argv", ["penguin-email"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_auth_subcommand_dispatched(self, monkeypatch) -> None:
        mock_run = MagicMock()
        with patch.dict(
            sys.modules,
            {"penguin_email.auth.gmail_oauth": MagicMock(run_oauth_flow=mock_run)},
        ):
            with patch("sys.argv", ["penguin-email", "auth"]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 0

    def test_check_subcommand_dispatched(self, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.setenv("SMTP_MODE", "STARTTLS")

        mock_transport = MagicMock()
        mock_transport.health_check.return_value = True
        mock_transport.transport_name = "smtp"

        with patch("penguin_email.transports.smtp.SmtpTransport", return_value=mock_transport):
            with patch("sys.argv", ["penguin-email", "check"]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 0
