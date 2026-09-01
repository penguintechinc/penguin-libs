"""Exception hierarchy for penguin-sal."""

from __future__ import annotations

import re

# Matches the userinfo segment of a connection URI immediately following
# "://" (or a bare "//"), e.g. "user:s3cr3t@" in "redis://user:s3cr3t@host".
# Deliberately tolerant of malformed/unparseable URIs (invalid hosts,
# stray whitespace, etc.) since InvalidURIError is raised precisely when
# the URI failed to parse cleanly - redaction must not depend on the URI
# being well-formed.
_URI_USERINFO_RE = re.compile(r"//(?P<userinfo>[^/@\s]+)@")


def _redact_uri(uri: str) -> str:
    """Strip credentials from a connection URI before it is displayed.

    Replaces any `user:pass@` (or `user@`) segment following `//` with a
    fixed placeholder so plaintext backend credentials never reach
    exception messages, logs, or tracebacks - even for malformed URIs
    that fail parsing.
    """
    return _URI_USERINFO_RE.sub("//***@", uri)


class PySecretsError(Exception):
    """Base exception for all penguin-sal errors."""


class ConnectionError(PySecretsError):
    """Failed to connect to the secrets backend."""


class AuthenticationError(PySecretsError):
    """Authentication with the secrets backend failed."""


class AuthorizationError(PySecretsError):
    """Insufficient permissions for the requested operation."""


class SecretNotFoundError(PySecretsError):
    """The requested secret does not exist."""

    def __init__(self, key: str, backend: str | None = None) -> None:
        self.key = key
        self.backend = backend
        msg = f"Secret not found: {key}"
        if backend:
            msg += f" (backend: {backend})"
        super().__init__(msg)


class InvalidURIError(PySecretsError):
    """The connection URI is malformed or unsupported."""

    def __init__(self, uri: str, reason: str = "") -> None:
        redacted = _redact_uri(uri)
        self.uri = redacted
        self.reason = reason
        msg = f"Invalid URI: {redacted}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class InvalidSecretValueError(PySecretsError):
    """The secret value is invalid or cannot be processed."""


class BackendError(PySecretsError):
    """An error occurred in the secrets backend."""

    def __init__(
        self,
        message: str,
        backend: str | None = None,
        original_error: BaseException | None = None,
    ) -> None:
        self.backend = backend
        self.original_error = original_error
        msg = message
        if backend:
            msg = f"[{backend}] {msg}"
        super().__init__(msg)


class RetryExhaustedError(PySecretsError):
    """All retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: BaseException | None = None) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"All {attempts} retry attempts exhausted")


class AdapterNotInstalledError(PySecretsError):
    """The required SDK/client for the adapter is not installed."""

    def __init__(self, adapter_name: str, install_extra: str) -> None:
        self.adapter_name = adapter_name
        self.install_extra = install_extra
        super().__init__(
            f"Backend '{adapter_name}' requires additional dependencies. "
            f"Install with: pip install penguin-sal[{install_extra}]"
        )
