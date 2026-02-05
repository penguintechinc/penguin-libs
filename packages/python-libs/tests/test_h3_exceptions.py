"""Tests for penguin_libs.h3.exceptions module."""

import pytest

from penguin_libs.h3.exceptions import (
    H3ClientError,
    H3ConfigError,
    H3Error,
    H3ServerError,
    H3TLSError,
    ProtocolFallbackError,
)


def test_h3_error_is_exception():
    """Test that H3Error is a subclass of Exception."""
    assert issubclass(H3Error, Exception)
    error = H3Error("test error")
    assert isinstance(error, Exception)
    assert str(error) == "test error"


def test_subclass_hierarchy():
    """Test that all H3 exceptions are subclasses of H3Error."""
    assert issubclass(H3ConfigError, H3Error)
    assert issubclass(H3TLSError, H3Error)
    assert issubclass(H3ServerError, H3Error)
    assert issubclass(H3ClientError, H3Error)
    assert issubclass(ProtocolFallbackError, H3Error)


def test_protocol_fallback_error_attributes():
    """Test ProtocolFallbackError stores original_error and fallback_protocol."""
    original = ValueError("connection failed")
    error = ProtocolFallbackError(
        original_error=original,
        protocol="h2"
    )
    assert error.original_error is original
    assert error.fallback_protocol == "h2"


def test_protocol_fallback_error_message():
    """Test ProtocolFallbackError message format."""
    original = ValueError("connection failed")
    error = ProtocolFallbackError(
        original_error=original,
        protocol="h2"
    )
    message = str(error)
    assert "HTTP/3 failed" in message
    assert "fell back to h2" in message
    assert "connection failed" in message


def test_all_exceptions_catchable_as_h3error():
    """Test that all H3 exceptions can be caught as H3Error."""
    exceptions = [
        H3ConfigError("config error"),
        H3TLSError("tls error"),
        H3ServerError("server error"),
        H3ClientError("client error"),
        ProtocolFallbackError(ValueError("test"), "h2"),
    ]

    for exc in exceptions:
        try:
            raise exc
        except H3Error as e:
            assert isinstance(e, H3Error)
        else:
            pytest.fail(f"Exception {exc} was not caught as H3Error")
