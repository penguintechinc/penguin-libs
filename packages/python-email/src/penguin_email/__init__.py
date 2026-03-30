"""penguin-email — pluggable email sending library for Penguin Tech applications."""

__version__ = "0.1.0"

from .client import EmailClient
from .message import EmailMessage
from .transports import EmailTransport, SendResult
from .transports.smtp import InsecureConnectionWarning, SmtpMode, SmtpTransport

__all__ = [
    "__version__",
    "EmailClient",
    "EmailMessage",
    "EmailTransport",
    "SendResult",
    "SmtpTransport",
    "SmtpMode",
    "InsecureConnectionWarning",
]

# GmailTransport is only importable when google-auth extras are installed.
# Import it lazily so SMTP-only users don't get an ImportError.
try:
    from .transports.gmail import GmailTransport  # noqa: F401

    __all__ = [*__all__, "GmailTransport"]
except ImportError:
    pass
