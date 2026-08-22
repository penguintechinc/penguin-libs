"""EmailClient — orchestrates message building, rendering, and sending."""

from __future__ import annotations

import logging

from .message import EmailMessage
from .signature import Signature
from .templates.engine import TemplateRenderer
from .transports import EmailTransport, SendResult

logger = logging.getLogger(__name__)


class EmailClient:
    """High-level email client that validates, renders, and dispatches messages.

    Parameters
    ----------
    transport:
        Primary :class:`~penguin_email.transports.EmailTransport`.
    fallback:
        Optional secondary transport used when *fallback_on_error* is ``True``
        and the primary transport raises an exception.
    fallback_on_error:
        When ``True``, a send error on the primary transport is logged and the
        fallback transport is tried.  Defaults to ``False`` (re-raise).
    default_signature:
        Optional :class:`~penguin_email.signature.Signature` appended to
        every message sent through this client. A signature attached
        directly to a message via
        :meth:`~penguin_email.message.EmailMessage.signature` overrides
        this default for that message only.

    Raises
    ------
    TypeError
        If *transport* (or *fallback*) does not implement the
        :class:`~penguin_email.transports.EmailTransport` protocol.
    """

    def __init__(
        self,
        transport: EmailTransport,
        fallback: EmailTransport | None = None,
        fallback_on_error: bool = False,
        default_signature: Signature | None = None,
    ) -> None:
        if not isinstance(transport, EmailTransport):
            raise TypeError(f"{transport!r} does not implement the EmailTransport protocol")
        if fallback is not None and not isinstance(fallback, EmailTransport):
            raise TypeError(f"{fallback!r} does not implement the EmailTransport protocol")
        self._transport = transport
        self._fallback = fallback
        self._fallback_on_error = fallback_on_error
        self._default_signature = default_signature
        self._renderer = TemplateRenderer()

    def send(self, message: EmailMessage) -> SendResult:
        """Validate, render, and send *message*.

        1. Calls :meth:`~penguin_email.message.EmailMessage.build` to validate.
        2. Renders the template (if any) into HTML.
        3. Appends the effective signature (message override or client
           default) to both the HTML and plain-text bodies.
        4. Tries the primary transport.
        5. Falls back to the secondary transport when configured.

        Returns a :class:`~penguin_email.transports.SendResult` with
        ``transport_used`` set to the name of the transport that succeeded (or
        attempted last).
        """
        if not message.is_built:
            message.build()

        self._render_message(message)
        self._apply_signature(message)

        try:
            return self._transport.send(message)
        except Exception as exc:
            if self._fallback_on_error and self._fallback is not None:
                logger.warning(
                    "Primary transport '%s' failed (%s), trying fallback '%s'",
                    self._transport.transport_name,
                    exc,
                    self._fallback.transport_name,
                )
                try:
                    return self._fallback.send(message)
                except Exception as fallback_exc:
                    logger.error(
                        "Fallback transport '%s' also failed: %s",
                        self._fallback.transport_name,
                        fallback_exc,
                    )
                    return SendResult(
                        success=False,
                        transport_used=self._fallback.transport_name,
                        error=str(fallback_exc),
                    )
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_message(self, message: EmailMessage) -> None:
        """Render the template (if any) and inject the result into the message.

        After rendering, ``message._html_body`` is set so the transport only
        needs to handle plain HTML.  This mutates the message in place.
        """
        if message.html_body:
            # Already has raw HTML — nothing to render.
            return

        if message.template_name:
            html = self._renderer.render_builtin(message.template_name, **message.template_kwargs)
            message._html_body = html  # noqa: SLF001
        elif message.template_path:
            html = self._renderer.render_file(message.template_path, **message.template_kwargs)
            message._html_body = html  # noqa: SLF001
        elif message.form_data is not None:
            html = self._renderer.render_builtin(
                "form",
                title=message.template_kwargs.get("title", "Form Submission"),
                data=message.form_data,
            )
            message._html_body = html  # noqa: SLF001

    def _apply_signature(self, message: EmailMessage) -> None:
        """Render the effective signature and append it to both bodies.

        A per-message signature (``EmailMessage.signature()``) overrides the
        client-wide ``default_signature``; if neither is set, the message is
        left completely untouched. This runs once, here, in the client —
        never in a transport — so every transport (SMTP, Gmail, SendGrid)
        receives an already-signed ``html_body``/``text_body`` and cannot
        forget to apply it.

        Every transport independently falls back to
        ``strip_tags(html_body)`` for the plain-text body when
        ``text_body`` is empty. To keep the signature's own text form (when
        supplied) out of that fallback — i.e. to avoid ending up with
        ``strip_tags(body_html + signature_html)`` instead of
        ``strip_tags(body_html) + signature.text`` — the body's
        auto-generated plain text is captured *before* the signature's HTML
        is appended, and the final ``text_body`` is written back here so
        transports see it already populated and skip their own fallback.
        """
        sig = message.signature_block or self._default_signature
        if sig is None:
            return

        # Capture the body's own auto-generated plain text before the
        # signature's HTML is merged in.
        base_text = message.text_body or (
            self._renderer.strip_tags(message.html_body) if message.html_body else ""
        )

        sig_html = self._renderer.render_string(sig.html, **sig.variables) if sig.html else ""
        if sig.text:
            sig_text = self._renderer.render_string(sig.text, autoescape=False, **sig.variables)
        elif sig_html:
            sig_text = self._renderer.strip_tags(sig_html)
        else:
            sig_text = ""

        if sig_html:
            message._html_body = message.html_body + sig_html  # noqa: SLF001

        message._text_body = f"{base_text}\n\n{sig_text}" if sig_text else base_text  # noqa: SLF001
