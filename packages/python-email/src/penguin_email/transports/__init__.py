"""Email transport protocol and shared result type.

DKIM signing (:mod:`penguin_email.dkim_signing`) is available on
:class:`~penguin_email.transports.smtp.SmtpTransport` only. Gmail and
SendGrid DKIM-sign outgoing mail on the sending domain's behalf as part of
their own delivery pipeline, so configuring DKIM signing for those
transports is unnecessary and risks double-signing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..message import EmailMessage


@dataclass(slots=True)
class SendResult:
    """Result returned by every transport after an attempt to send."""

    success: bool
    transport_used: str
    message_id: str = field(default="")
    error: str = field(default="")


@runtime_checkable
class EmailTransport(Protocol):
    """Structural protocol — any class with these members is a valid transport.

    Implement this protocol to add a new transport (Outlook, SendGrid, etc.)
    without modifying any core code.  ``@runtime_checkable`` allows
    ``isinstance(obj, EmailTransport)`` at runtime for validation in
    :class:`EmailClient.__init__`.
    """

    transport_name: str
    """Human-readable name used in :class:`SendResult.transport_used`."""

    def send(self, message: EmailMessage) -> SendResult:
        """Send *message* and return a :class:`SendResult`."""
        ...

    def health_check(self) -> bool:
        """Return ``True`` if the transport is reachable / credentials are valid."""
        ...
