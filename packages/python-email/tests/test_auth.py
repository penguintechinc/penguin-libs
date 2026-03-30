"""Tests for Gmail OAuth2 auth helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, call, mock_open, patch

import pytest


class TestRunOAuthFlow:
    def test_calls_installed_app_flow(self, tmp_path) -> None:
        token_path = str(tmp_path / "token.json")
        creds_path = "credentials.json"

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "abc"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch(
            "penguin_email.auth.gmail_oauth.InstalledAppFlow"
        ) as mock_flow_cls:
            mock_flow_cls.from_client_secrets_file.return_value = mock_flow
            from penguin_email.auth.gmail_oauth import run_oauth_flow

            run_oauth_flow(creds_path, token_path)

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            creds_path,
            ["https://www.googleapis.com/auth/gmail.send"],
        )
        mock_flow.run_local_server.assert_called_once_with(port=0)

    def test_token_written_to_path(self, tmp_path) -> None:
        token_path = str(tmp_path / "token.json")

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "xyz"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("penguin_email.auth.gmail_oauth.InstalledAppFlow") as mock_flow_cls:
            mock_flow_cls.from_client_secrets_file.return_value = mock_flow
            from penguin_email.auth.gmail_oauth import run_oauth_flow

            run_oauth_flow("credentials.json", token_path)

        with open(token_path) as f:
            content = f.read()
        assert content == '{"token": "xyz"}'


class TestRefreshCredentials:
    def test_refresh_calls_creds_refresh(self) -> None:
        mock_creds = MagicMock()
        mock_request = MagicMock()

        with patch("penguin_email.auth.gmail_oauth.Request", return_value=mock_request):
            from penguin_email.auth.gmail_oauth import refresh_credentials

            result = refresh_credentials(mock_creds)

        mock_creds.refresh.assert_called_once_with(mock_request)
        assert result is mock_creds
