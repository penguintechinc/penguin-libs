"""Tests for penguin-sal exception hierarchy."""

import pytest
from penguin_sal.core.exceptions import (
    PySecretsError,
    ConnectionError,
    AuthenticationError,
    AuthorizationError,
    SecretNotFoundError,
    InvalidURIError,
    InvalidSecretValueError,
    BackendError,
    RetryExhaustedError,
    AdapterNotInstalledError,
)


class TestBaseExceptionHierarchy:
    """Test base exception hierarchy."""

    def test_base_exception_hierarchy(self) -> None:
        """PySecretsError is subclass of Exception."""
        assert issubclass(PySecretsError, Exception)


class TestAllSubclasses:
    """Test all exception subclasses."""

    def test_all_subclasses(self) -> None:
        """All specific exceptions are subclasses of PySecretsError."""
        exceptions = [
            ConnectionError,
            AuthenticationError,
            AuthorizationError,
            SecretNotFoundError,
            InvalidURIError,
            InvalidSecretValueError,
            BackendError,
            RetryExhaustedError,
            AdapterNotInstalledError,
        ]
        for exc_class in exceptions:
            assert issubclass(exc_class, PySecretsError)


class TestSecretNotFoundError:
    """Test SecretNotFoundError exception."""

    def test_secret_not_found_attributes(self) -> None:
        """SecretNotFoundError stores key and backend, message contains both."""
        exc = SecretNotFoundError("my-key", "vault")
        assert exc.key == "my-key"
        assert exc.backend == "vault"
        msg = str(exc)
        assert "my-key" in msg
        assert "vault" in msg

    def test_secret_not_found_no_backend(self) -> None:
        """SecretNotFoundError without backend doesn't contain backend in message."""
        exc = SecretNotFoundError("my-key")
        assert exc.key == "my-key"
        assert exc.backend is None
        msg = str(exc)
        assert "my-key" in msg
        assert "backend" not in msg


class TestInvalidURIError:
    """Test InvalidURIError exception."""

    def test_invalid_uri_attributes(self) -> None:
        """InvalidURIError stores uri and reason."""
        exc = InvalidURIError("bad://uri", "unsupported")
        assert exc.uri == "bad://uri"
        assert exc.reason == "unsupported"
        msg = str(exc)
        assert "bad://uri" in msg
        assert "unsupported" in msg

    def test_invalid_uri_no_reason(self) -> None:
        """InvalidURIError without reason has basic message."""
        exc = InvalidURIError("bad://uri")
        assert exc.uri == "bad://uri"
        assert exc.reason == ""
        msg = str(exc)
        assert msg == "Invalid URI: bad://uri"


class TestBackendError:
    """Test BackendError exception."""

    def test_backend_error_attributes(self) -> None:
        """BackendError stores message, backend, and original_error."""
        original = ValueError("x")
        exc = BackendError("failed", "vault", original_error=original)
        assert exc.backend == "vault"
        assert exc.original_error is original
        msg = str(exc)
        assert "failed" in msg
        assert "vault" in msg

    def test_backend_error_no_backend(self) -> None:
        """BackendError without backend has message without brackets."""
        exc = BackendError("failed")
        assert exc.backend is None
        assert exc.original_error is None
        msg = str(exc)
        assert msg == "failed"


class TestRetryExhaustedError:
    """Test RetryExhaustedError exception."""

    def test_retry_exhausted_attributes(self) -> None:
        """RetryExhaustedError stores attempts and last_error."""
        last_err = ValueError("x")
        exc = RetryExhaustedError(3, last_err)
        assert exc.attempts == 3
        assert exc.last_error is last_err
        msg = str(exc)
        assert "3" in msg


class TestAdapterNotInstalledError:
    """Test AdapterNotInstalledError exception."""

    def test_adapter_not_installed(self) -> None:
        """AdapterNotInstalledError stores adapter_name and install_extra with install instruction."""
        exc = AdapterNotInstalledError("vault", "vault")
        assert exc.adapter_name == "vault"
        assert exc.install_extra == "vault"
        msg = str(exc)
        assert "vault" in msg
        assert "pip install" in msg


class TestAllCatchableAsBase:
    """Test that all exceptions can be caught as base PySecretsError."""

    def test_all_catchable_as_base(self) -> None:
        """All exception types can be caught with except PySecretsError."""
        exceptions = [
            ConnectionError("test"),
            AuthenticationError("test"),
            AuthorizationError("test"),
            SecretNotFoundError("key"),
            InvalidURIError("uri"),
            InvalidSecretValueError("test"),
            BackendError("test"),
            RetryExhaustedError(1),
            AdapterNotInstalledError("test", "test"),
        ]
        for exc in exceptions:
            try:
                raise exc
            except PySecretsError:
                pass  # Expected
            except Exception:
                pytest.fail(f"{type(exc).__name__} not catchable as PySecretsError")
