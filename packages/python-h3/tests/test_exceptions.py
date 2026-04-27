"""Tests for H3 exception classes."""

from __future__ import annotations

import pytest

from penguin_h3.exceptions import (
    H3ClientError,
    H3ConfigError,
    H3Error,
    H3ServerError,
    H3TLSError,
    ProtocolFallbackError,
)


class TestH3Error:
    """Test H3Error base exception."""

    def test_h3_error_raised(self) -> None:
        """Test that H3Error can be raised and caught."""
        with pytest.raises(H3Error):
            raise H3Error("test error")

    def test_h3_error_message(self) -> None:
        """Test that H3Error preserves error message."""
        msg = "something went wrong"
        try:
            raise H3Error(msg)
        except H3Error as exc:
            assert str(exc) == msg

    def test_h3_error_is_exception(self) -> None:
        """Test that H3Error inherits from Exception."""
        assert issubclass(H3Error, Exception)


class TestH3ConfigError:
    """Test H3ConfigError exception."""

    def test_h3_config_error_raised(self) -> None:
        """Test that H3ConfigError can be raised and caught."""
        with pytest.raises(H3ConfigError):
            raise H3ConfigError("invalid config")

    def test_h3_config_error_message(self) -> None:
        """Test that H3ConfigError preserves error message."""
        msg = "config validation failed"
        try:
            raise H3ConfigError(msg)
        except H3ConfigError as exc:
            assert str(exc) == msg

    def test_h3_config_error_inherits_from_h3_error(self) -> None:
        """Test that H3ConfigError inherits from H3Error."""
        assert issubclass(H3ConfigError, H3Error)

    def test_h3_config_error_caught_as_h3_error(self) -> None:
        """Test that H3ConfigError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ConfigError("invalid config")


class TestH3TLSError:
    """Test H3TLSError exception."""

    def test_h3_tls_error_raised(self) -> None:
        """Test that H3TLSError can be raised and caught."""
        with pytest.raises(H3TLSError):
            raise H3TLSError("tls error")

    def test_h3_tls_error_message(self) -> None:
        """Test that H3TLSError preserves error message."""
        msg = "certificate not found"
        try:
            raise H3TLSError(msg)
        except H3TLSError as exc:
            assert str(exc) == msg

    def test_h3_tls_error_inherits_from_h3_error(self) -> None:
        """Test that H3TLSError inherits from H3Error."""
        assert issubclass(H3TLSError, H3Error)

    def test_h3_tls_error_caught_as_h3_error(self) -> None:
        """Test that H3TLSError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3TLSError("tls error")


class TestH3ServerError:
    """Test H3ServerError exception."""

    def test_h3_server_error_raised(self) -> None:
        """Test that H3ServerError can be raised and caught."""
        with pytest.raises(H3ServerError):
            raise H3ServerError("server error")

    def test_h3_server_error_message(self) -> None:
        """Test that H3ServerError preserves error message."""
        msg = "failed to bind port"
        try:
            raise H3ServerError(msg)
        except H3ServerError as exc:
            assert str(exc) == msg

    def test_h3_server_error_inherits_from_h3_error(self) -> None:
        """Test that H3ServerError inherits from H3Error."""
        assert issubclass(H3ServerError, H3Error)

    def test_h3_server_error_caught_as_h3_error(self) -> None:
        """Test that H3ServerError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ServerError("server error")


class TestH3ClientError:
    """Test H3ClientError exception."""

    def test_h3_client_error_raised(self) -> None:
        """Test that H3ClientError can be raised and caught."""
        with pytest.raises(H3ClientError):
            raise H3ClientError("client error")

    def test_h3_client_error_message(self) -> None:
        """Test that H3ClientError preserves error message."""
        msg = "connection failed"
        try:
            raise H3ClientError(msg)
        except H3ClientError as exc:
            assert str(exc) == msg

    def test_h3_client_error_inherits_from_h3_error(self) -> None:
        """Test that H3ClientError inherits from H3Error."""
        assert issubclass(H3ClientError, H3Error)

    def test_h3_client_error_caught_as_h3_error(self) -> None:
        """Test that H3ClientError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ClientError("client error")


class TestProtocolFallbackError:
    """Test ProtocolFallbackError exception."""

    def test_protocol_fallback_error_basic(self) -> None:
        """Test ProtocolFallbackError with original error."""
        original = ValueError("h3 connection failed")
        exc = ProtocolFallbackError(original)

        assert exc.original_error == original
        assert exc.fallback_protocol == "h2"
        assert "h3" in str(exc).lower()
        assert "h2" in str(exc).lower()

    def test_protocol_fallback_error_custom_protocol(self) -> None:
        """Test ProtocolFallbackError with custom fallback protocol."""
        original = RuntimeError("quic error")
        exc = ProtocolFallbackError(original, protocol="custom")

        assert exc.original_error == original
        assert exc.fallback_protocol == "custom"
        assert "custom" in str(exc)

    def test_protocol_fallback_error_message_format(self) -> None:
        """Test ProtocolFallbackError message format."""
        original = TimeoutError("connection timeout")
        exc = ProtocolFallbackError(original, protocol="h2")

        msg = str(exc)
        assert "HTTP/3" in msg
        assert "connection timeout" in msg
        assert "h2" in msg

    def test_protocol_fallback_error_inherits_from_h3_error(self) -> None:
        """Test that ProtocolFallbackError inherits from H3Error."""
        assert issubclass(ProtocolFallbackError, H3Error)

    def test_protocol_fallback_error_caught_as_h3_error(self) -> None:
        """Test that ProtocolFallbackError can be caught as H3Error."""
        original = Exception("some error")
        with pytest.raises(H3Error):
            raise ProtocolFallbackError(original)

    def test_protocol_fallback_error_attributes_preserved(self) -> None:
        """Test that ProtocolFallbackError preserves original exception details."""
        original = ValueError("specific error message")
        exc = ProtocolFallbackError(original)

        # Check that original exception is accessible
        assert isinstance(exc.original_error, ValueError)
        assert str(exc.original_error) == "specific error message"
