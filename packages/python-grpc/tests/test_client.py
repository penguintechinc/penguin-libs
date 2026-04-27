"""Tests for gRPC client wrapper."""

import time
from unittest.mock import MagicMock, Mock, patch

import grpc
import pytest

from penguin_grpc.client import ClientOptions, GrpcClient


class TestClientOptions:
    """Test ClientOptions dataclass."""

    def test_default_values(self) -> None:
        """Test ClientOptions has correct defaults."""
        opts = ClientOptions()
        assert opts.max_retries == 3
        assert opts.initial_backoff_ms == 100
        assert opts.max_backoff_ms == 5000
        assert opts.backoff_multiplier == 2.0
        assert opts.timeout_seconds == 30.0
        assert opts.enable_tls is False
        assert opts.ca_cert_path is None
        assert opts.client_cert_path is None
        assert opts.client_key_path is None
        assert opts.keepalive_time_ms == 60000
        assert opts.keepalive_timeout_ms == 20000

    def test_custom_values(self) -> None:
        """Test ClientOptions with custom values."""
        opts = ClientOptions(
            max_retries=5,
            timeout_seconds=60.0,
            enable_tls=True,
            ca_cert_path="/path/to/ca.pem",
        )
        assert opts.max_retries == 5
        assert opts.timeout_seconds == 60.0
        assert opts.enable_tls is True
        assert opts.ca_cert_path == "/path/to/ca.pem"

    def test_frozen_dataclass(self) -> None:
        """Test ClientOptions is frozen."""
        opts = ClientOptions()
        with pytest.raises(AttributeError):
            opts.max_retries = 10  # type: ignore


class TestGrpcClient:
    """Test GrpcClient wrapper."""

    def test_client_init(self) -> None:
        """Test GrpcClient initialization."""
        client = GrpcClient("localhost:50051")
        assert client.target == "localhost:50051"
        assert isinstance(client.options, ClientOptions)
        assert client._channel is None

    def test_client_init_with_custom_options(self) -> None:
        """Test GrpcClient with custom options."""
        opts = ClientOptions(timeout_seconds=60.0)
        client = GrpcClient("localhost:50051", options=opts)
        assert client.options.timeout_seconds == 60.0

    def test_client_channel_creation(self) -> None:
        """Test gRPC channel is created."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock(spec=grpc.Channel)
            client = GrpcClient("localhost:50051")
            channel = client.channel()
            assert channel is not None
            mock_channel.assert_called_once()

    def test_client_channel_reuses_existing(self) -> None:
        """Test channel is reused on subsequent calls."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj
            client = GrpcClient("localhost:50051")

            channel1 = client.channel()
            channel2 = client.channel()

            assert channel1 is channel2
            mock_channel.assert_called_once()

    def test_client_insecure_channel(self) -> None:
        """Test insecure channel creation."""
        with patch("grpc.insecure_channel") as mock_insecure:
            mock_insecure.return_value = MagicMock(spec=grpc.Channel)
            client = GrpcClient("localhost:50051")
            client.channel()
            mock_insecure.assert_called_once()

    def test_client_secure_channel(self) -> None:
        """Test secure TLS channel creation."""
        with patch("grpc.secure_channel") as mock_secure:
            with patch.object(GrpcClient, "_create_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()
                mock_secure.return_value = MagicMock(spec=grpc.Channel)

                opts = ClientOptions(enable_tls=True)
                client = GrpcClient("localhost:50051", options=opts)
                client.channel()

                mock_secure.assert_called_once()
                mock_creds.assert_called_once()

    def test_create_credentials_with_ca_cert(self) -> None:
        """Test credentials creation with CA certificate."""
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b"ca_cert"
            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()

                opts = ClientOptions(
                    enable_tls=True,
                    ca_cert_path="/path/to/ca.pem",
                )
                client = GrpcClient("localhost:50051", options=opts)
                client._create_credentials()

                mock_creds.assert_called_once()

    def test_create_credentials_with_client_cert(self) -> None:
        """Test credentials creation with client certificate."""
        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = b"cert_data"
            mock_open.return_value = mock_file

            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()

                opts = ClientOptions(
                    enable_tls=True,
                    client_cert_path="/path/to/cert.pem",
                    client_key_path="/path/to/key.pem",
                )
                client = GrpcClient("localhost:50051", options=opts)
                client._create_credentials()

                mock_creds.assert_called_once()

    def test_call_with_retry_success(self) -> None:
        """Test successful RPC call without retry."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        result = client.call_with_retry(mock_func, "request")

        assert result == "response"
        mock_func.assert_called_once()

    def test_call_with_retry_sets_default_timeout(self) -> None:
        """Test default timeout is set if not provided."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        client.call_with_retry(mock_func, "request")

        call_kwargs = mock_func.call_args[1]
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] == 30.0

    def test_call_with_retry_respects_custom_timeout(self) -> None:
        """Test custom timeout is preserved."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        client.call_with_retry(mock_func, "request", timeout=60.0)

        call_kwargs = mock_func.call_args[1]
        assert call_kwargs["timeout"] == 60.0

    def test_call_with_retry_retries_transient_errors(self) -> None:
        """Test transient errors trigger retries."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=3))
        mock_func = MagicMock()

        # Fail twice, succeed on third attempt
        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, "success"]

        with patch("time.sleep"):
            result = client.call_with_retry(mock_func)
            assert result == "success"
            assert mock_func.call_count == 3

    def test_call_with_retry_non_retryable_errors(self) -> None:
        """Test non-retryable errors are raised immediately."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=3))
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.INVALID_ARGUMENT)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        # Should be called only once (no retries)
        assert mock_func.call_count == 1

    def test_call_with_retry_unauthorized_not_retried(self) -> None:
        """Test UNAUTHENTICATED errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAUTHENTICATED)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_permission_denied_not_retried(self) -> None:
        """Test PERMISSION_DENIED errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.PERMISSION_DENIED)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_not_found_not_retried(self) -> None:
        """Test NOT_FOUND errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.NOT_FOUND)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_already_exists_not_retried(self) -> None:
        """Test ALREADY_EXISTS errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.ALREADY_EXISTS)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_exponential_backoff(self) -> None:
        """Test exponential backoff is applied."""
        client = GrpcClient(
            "localhost:50051",
            options=ClientOptions(
                max_retries=3,
                initial_backoff_ms=100,
                backoff_multiplier=2.0,
            ),
        )
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, "success"]

        with patch("time.sleep") as mock_sleep:
            client.call_with_retry(mock_func)

            # Should sleep with exponential backoff: 100ms, then 200ms
            assert mock_sleep.call_count == 2
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert sleep_calls[0] == 0.1  # 100ms
            assert sleep_calls[1] == 0.2  # 200ms

    def test_call_with_retry_max_backoff_cap(self) -> None:
        """Test backoff is capped at max value."""
        client = GrpcClient(
            "localhost:50051",
            options=ClientOptions(
                max_retries=5,
                initial_backoff_ms=100,
                max_backoff_ms=500,
                backoff_multiplier=2.0,
            ),
        )
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, error, "success"]

        with patch("time.sleep") as mock_sleep:
            client.call_with_retry(mock_func)

            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            # 100, 200, 400 (capped at 500)
            assert sleep_calls[2] == 0.4  # capped at 400ms

    def test_client_close(self) -> None:
        """Test client channel is properly closed."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            client = GrpcClient("localhost:50051")
            client.channel()
            client.close()

            mock_channel_obj.close.assert_called_once()
            assert client._channel is None

    def test_client_context_manager(self) -> None:
        """Test client works as context manager."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            with GrpcClient("localhost:50051") as client:
                channel = client.channel()
                assert channel is not None

            mock_channel_obj.close.assert_called_once()

    def test_client_context_manager_cleanup_on_exception(self) -> None:
        """Test client cleans up on exception in context manager."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            try:
                with GrpcClient("localhost:50051") as client:
                    client.channel()
                    raise ValueError("Test error")
            except ValueError:
                pass

            mock_channel_obj.close.assert_called_once()

    def test_client_retry_all_retries_exhausted(self) -> None:
        """Test exception raised when all retries exhausted."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=2))
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = error

        with patch("time.sleep"):
            with pytest.raises(grpc.RpcError):
                client.call_with_retry(mock_func)

            # Should attempt 2 times
            assert mock_func.call_count == 2

    def test_call_with_retry_positional_args(self) -> None:
        """Test call_with_retry passes positional arguments."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        result = client.call_with_retry(mock_func, "arg1", "arg2", kwarg1="value1")

        assert result == "response"
        mock_func.assert_called_once_with("arg1", "arg2", kwarg1="value1", timeout=30.0)

    def test_channel_options_applied(self) -> None:
        """Test channel options are properly applied."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock(spec=grpc.Channel)

            opts = ClientOptions(
                keepalive_time_ms=30000,
                keepalive_timeout_ms=10000,
            )
            client = GrpcClient("localhost:50051", options=opts)
            client.channel()

            # Verify channel options were set
            call_kwargs = mock_channel.call_args[1]
            assert "options" in call_kwargs
            options = call_kwargs["options"]
            option_dict = dict(options)
            assert option_dict["grpc.keepalive_time_ms"] == 30000
            assert option_dict["grpc.keepalive_timeout_ms"] == 10000
