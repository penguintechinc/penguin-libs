"""DKIM signing configuration and signer for outgoing SMTP mail.

Only :class:`~penguin_email.transports.smtp.SmtpTransport` uses this module.
:class:`~penguin_email.transports.gmail.GmailTransport` and
:class:`~penguin_email.transports.sendgrid.SendGridTransport` deliver through
Gmail's and SendGrid's own APIs, and **both providers DKIM-sign outgoing mail
on the sending domain's behalf already**. Configuring a
:class:`DkimConfig` for those paths is unnecessary and risks double-signing
(or signing with the wrong selector/key) -- DKIM signing here applies to the
raw SMTP relay path only.

Requires the ``[dkim]`` extra::

    pip install "penguin-email[dkim]"

Named ``dkim_signing`` rather than ``dkim`` to avoid shadowing the
third-party ``dkimpy`` package (imported as ``dkim``) that this module
wraps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Module-level import so unittest.mock.patch can target it by module path.
# Set to None when the [dkim] extra is not installed.
try:
    import dkim as _dkimpy  # type: ignore[import-untyped]
except ImportError:
    _dkimpy = None


class DkimSigningError(Exception):
    """Raised when a configured DKIM signature could not be produced.

    The message is always a fixed, generic summary -- it never includes the
    private key material or any part of the underlying library's exception
    text, which (depending on failure mode) may otherwise echo fragments of
    the malformed key. Safe to log or place in :attr:`SendResult.error`.
    """


@dataclass(slots=True, repr=False)
class DkimConfig:
    """DKIM signing parameters for :class:`~penguin_email.transports.smtp.SmtpTransport`.

    ``private_key`` holds PEM-encoded key material already read into memory
    by the caller. Construct via :meth:`from_env` or :meth:`from_file`
    rather than passing a key literal -- the key must come from an
    environment variable or a file path, never a default value in code or
    anything checked into the repo.
    """

    domain: str
    selector: str
    private_key: str

    @classmethod
    def from_env(
        cls,
        *,
        domain_var: str = "DKIM_DOMAIN",
        selector_var: str = "DKIM_SELECTOR",
        private_key_var: str = "DKIM_PRIVATE_KEY",
    ) -> DkimConfig:
        """Build config from environment variables.

        ``private_key_var`` must hold the PEM-encoded private key text
        itself (not a path) -- use :meth:`from_file` to source the key from
        a mounted secret file instead.
        """
        return cls(
            domain=os.environ[domain_var],
            selector=os.environ[selector_var],
            private_key=os.environ[private_key_var],
        )

    @classmethod
    def from_file(cls, *, domain: str, selector: str, private_key_path: str) -> DkimConfig:
        """Build config with the private key read from *private_key_path*.

        Suited to secrets mounted as files (Vault, Kubernetes Secret volume,
        etc.) rather than inlined into the environment.
        """
        key_text = Path(private_key_path).read_text(encoding="utf-8")
        return cls(domain=domain, selector=selector, private_key=key_text)

    def __repr__(self) -> str:
        """Redact the private key -- default dataclass repr would print it verbatim."""
        return (
            f"DkimConfig(domain={self.domain!r}, selector={self.selector!r}, "
            "private_key=<redacted>)"
        )


class DkimSigner:
    """Wraps ``dkimpy`` to DKIM-sign a MIME message for ``SmtpTransport``.

    Raises :class:`ImportError` at construction time if the ``[dkim]``
    extra is not installed, matching the guard pattern used by
    :class:`~penguin_email.transports.gmail.GmailTransport` and
    :class:`~penguin_email.transports.sendgrid.SendGridTransport` -- this
    makes a missing optional dependency fail immediately, not on first send.
    """

    def __init__(self, config: DkimConfig) -> None:
        if _dkimpy is None:
            raise ImportError(
                "DKIM signing requires dkimpy. Install with: pip install 'penguin-email[dkim]'"
            )
        self._config = config

    def sign(self, message_bytes: bytes) -> bytes:
        """Return *message_bytes* prefixed with a ``DKIM-Signature`` header.

        The caller must send exactly the returned bytes unmodified -- DKIM
        signs the specific byte sequence handed in, so re-serializing the
        message afterward invalidates the signature.

        Raises :class:`DkimSigningError` if signing fails for any reason
        (malformed key, dkimpy internal error, etc.). The private key is
        never included in the raised exception.
        """
        try:
            signature_header: bytes = _dkimpy.sign(
                message=message_bytes,
                selector=self._config.selector.encode("ascii"),
                domain=self._config.domain.encode("ascii"),
                privkey=self._config.private_key.encode("ascii"),
                linesep=_dkimpy.util.get_linesep(message_bytes),
            )
        except Exception as exc:
            raise DkimSigningError(
                f"DKIM signing failed for domain {self._config.domain!r} "
                f"selector {self._config.selector!r}: {type(exc).__name__}"
            ) from None
        return signature_header + message_bytes
