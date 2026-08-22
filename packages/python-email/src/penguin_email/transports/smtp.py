"""SMTP transport (SSL / STARTTLS / PLAIN)."""

from __future__ import annotations

import logging
import smtplib
import warnings
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ..dkim_signing import DkimConfig, DkimSigner
from . import SendResult

if TYPE_CHECKING:
    from ..message import EmailMessage

logger = logging.getLogger(__name__)

_DEFAULT_PORTS: dict[str, int] = {
    "ssl": 465,
    "starttls": 587,
    "plain": 25,
}


class InsecureConnectionWarning(UserWarning):
    """Emitted whenever an email is sent over an unencrypted SMTP connection.

    Callers can suppress this warning if they have made a conscious decision
    to use plaintext SMTP::

        import warnings
        from penguin_email import InsecureConnectionWarning
        warnings.filterwarnings("ignore", category=InsecureConnectionWarning)
    """


class SmtpMode(Enum):
    """SMTP connection security mode."""

    SSL = "ssl"
    """Use :class:`smtplib.SMTP_SSL` (default port 465)."""

    STARTTLS = "starttls"
    """Use :class:`smtplib.SMTP` and upgrade with ``.starttls()`` (default port 587)."""

    PLAIN = "plain"
    """Unencrypted SMTP.  An :class:`InsecureConnectionWarning` is emitted on
    every send call."""


class SmtpTransport:
    """Send email via SMTP.

    Supports SSL, STARTTLS, and plain (unencrypted) connections.

    Pass *dkim* to DKIM-sign every outgoing message. DKIM signing here is
    opt-in and applies to this SMTP path only --
    :class:`~penguin_email.transports.gmail.GmailTransport` and
    :class:`~penguin_email.transports.sendgrid.SendGridTransport` already
    DKIM-sign on the sending domain's behalf; configuring
    :class:`~penguin_email.dkim_signing.DkimConfig` on those transports is
    unnecessary and risks double-signing. See
    :mod:`penguin_email.dkim_signing` for details. Requires the ``[dkim]``
    extra.
    """

    transport_name: str = "smtp"

    def __init__(
        self,
        host: str,
        port: int | None = None,
        mode: SmtpMode = SmtpMode.STARTTLS,
        username: str = "",
        # Empty default means "no password supplied" (plain/unauthenticated relay).
        password: str = "",  # nosec B107
        timeout: int = 30,
        dkim: DkimConfig | None = None,
    ) -> None:
        self._host = host
        self._port = port if port is not None else _DEFAULT_PORTS[mode.value]
        self._mode = mode
        self._username = username
        self._password = password
        self._timeout = timeout
        # Constructing the signer here (rather than lazily on first send)
        # fails fast: a missing [dkim] extra raises ImportError immediately
        # instead of on the first call to send().
        self._dkim_signer: DkimSigner | None = DkimSigner(dkim) if dkim is not None else None

    # ------------------------------------------------------------------
    # Transport interface
    # ------------------------------------------------------------------

    def send(self, message: EmailMessage) -> SendResult:
        """Send *message* via SMTP.

        Emits :class:`InsecureConnectionWarning` on every call when
        :attr:`SmtpMode.PLAIN` is in use.

        When a :class:`~penguin_email.dkim_signing.DkimConfig` was supplied
        at construction, the assembled MIME message is DKIM-signed
        immediately before handoff to :mod:`smtplib`, and the exact signed
        bytes are what gets sent. If signing fails, the send fails loudly --
        this method returns ``SendResult(success=False, ...)`` and no
        connection is opened; it never falls back to delivering the message
        unsigned.
        """
        if self._mode == SmtpMode.PLAIN:
            warnings.warn(
                "Email is being sent over an unencrypted SMTP connection. "
                "Use SmtpMode.SSL or SmtpMode.STARTTLS for production use.",
                InsecureConnectionWarning,
                stacklevel=2,
            )

        try:
            mime = self._build_mime(message)
            all_recipients = message.recipients + message.cc_recipients + message.bcc_recipients

            # DKIM signs a specific byte sequence -- once signed, that exact
            # sequence must reach smtplib unmodified, so the signed path
            # switches to bytes rather than re-serializing via as_string().
            raw_message: str | bytes
            if self._dkim_signer is not None:
                raw_message = self._dkim_signer.sign(mime.as_bytes())
            else:
                raw_message = mime.as_string()

            with self._connect() as conn:
                if self._username and self._password:
                    conn.login(self._username, self._password)
                conn.sendmail(
                    message.sender or self._username,
                    all_recipients,
                    raw_message,
                )

            return SendResult(
                success=True,
                transport_used=self.transport_name,
            )
        except Exception as exc:
            # DkimSigningError's message is a fixed, key-free summary (see
            # dkim_signing.py), so it is always safe to log/surface here
            # alongside every other transport failure.
            logger.error("SmtpTransport send error: %s", exc)
            return SendResult(
                success=False,
                transport_used=self.transport_name,
                error=str(exc),
            )

    def health_check(self) -> bool:
        """Open a connection, send EHLO, and close.  Returns ``True`` on success."""
        try:
            with self._connect() as conn:
                conn.ehlo()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> smtplib.SMTP:
        if self._mode == SmtpMode.SSL:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout)
        else:
            conn = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
            if self._mode == SmtpMode.STARTTLS:
                conn.starttls()
        return conn

    def _build_mime(self, message: EmailMessage) -> MIMEMultipart:
        """Construct the MIME message tree."""
        inline = [a for a in message.attachments if a.cid is not None]
        regular = [a for a in message.attachments if a.cid is None]

        outer: MIMEMultipart
        if inline:
            outer = MIMEMultipart("related")
            alt = MIMEMultipart("alternative")
            outer.attach(alt)
        elif regular:
            outer = MIMEMultipart("mixed")
            alt = MIMEMultipart("alternative")
            outer.attach(alt)
        else:
            outer = MIMEMultipart("alternative")
            alt = outer

        if message.sender:
            outer["From"] = message.sender
        outer["To"] = ", ".join(message.recipients)
        if message.cc_recipients:
            outer["Cc"] = ", ".join(message.cc_recipients)
        if message.reply_to_addr:
            outer["Reply-To"] = message.reply_to_addr
        outer["Subject"] = message.subject_line

        plain = message.text_body or ""
        if not plain and message.html_body:
            from ..templates.engine import TemplateRenderer

            plain = TemplateRenderer().strip_tags(message.html_body)
        if plain:
            alt.attach(MIMEText(plain, "plain", "utf-8"))

        if message.html_body:
            alt.attach(MIMEText(message.html_body, "html", "utf-8"))

        for att in inline:
            data = att.data or Path(att.path or "").read_bytes()
            img = MIMEImage(data, _subtype=att.content_type.split("/")[-1])
            img.add_header("Content-ID", f"<{att.cid}>")
            img.add_header("Content-Disposition", "inline", filename=att.filename)
            outer.attach(img)

        for att in regular:
            data = att.data or Path(att.path or "").read_bytes()
            part = MIMEApplication(data)
            part.add_header("Content-Disposition", "attachment", filename=att.filename)
            outer.attach(part)

        return outer
