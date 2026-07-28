"""EmailClient — orchestrates message building, rendering, and sending."""

from __future__ import annotations

import logging

from .message import EmailMessage
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
    ) -> None:
        if not isinstance(transport, EmailTransport):
            raise TypeError(
                f"{transport!r} does not implement the EmailTransport protocol"
            )
        if fallback is not None and not isinstance(fallback, EmailTransport):
            raise TypeError(
                f"{fallback!r} does not implement the EmailTransport protocol"
            )
        self._transport = transport
        self._fallback = fallback
        self._fallback_on_error = fallback_on_error
        self._renderer = TemplateRenderer()

    def send(self, message: EmailMessage) -> SendResult:
        """Validate, render, and send *message*.

        1. Calls :meth:`~penguin_email.message.EmailMessage.build` to validate.
        2. Renders the template (if any) into HTML.
        3. Tries the primary transport.
        4. Falls back to the secondary transport when configured.

        Returns a :class:`~penguin_email.transports.SendResult` with
        ``transport_used`` set to the name of the transport that succeeded (or
        attempted last).
        """
        if not message.is_built:
            message.build()

        self._render_message(message)

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
            html = self._renderer.render_builtin(
                message.template_name, **message.template_kwargs
            )
            message._html_body = html  # noqa: SLF001
        elif message.template_path:
            html = self._renderer.render_file(
                message.template_path, **message.template_kwargs
            )
            message._html_body = html  # noqa: SLF001
        elif message.form_data is not None:
            html = self._renderer.render_builtin(
                "form",
                title=message.template_kwargs.get("title", "Form Submission"),
                data=message.form_data,
            )
            message._html_body = html  # noqa: SLF001
