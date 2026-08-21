"""Per-sender signature blocks appended to outgoing mail.

A :class:`Signature` is attached either per-message
(:meth:`~penguin_email.message.EmailMessage.signature`) or as a client-wide
default (``EmailClient(default_signature=...)``). A per-message signature
always overrides the client default — see
:meth:`~penguin_email.client.EmailClient._apply_signature`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Signature:
    """An HTML + plain-text sign-off appended after a message's body.

    Both *html* and *text* may contain Jinja2 placeholders (e.g.
    ``{{ sender_name }}``) resolved against *variables* via the same
    :class:`~penguin_email.templates.engine.TemplateRenderer` used for
    message templates — no second templating path is introduced.

    If *text* is omitted, the text form is derived from the rendered *html*
    via :meth:`~penguin_email.templates.engine.TemplateRenderer.strip_tags`.
    Supplying a distinct *text* is preferred whenever the HTML signature
    contains layout markup (tables, images) that would strip down poorly.
    """

    html: str
    text: str = field(default="")
    variables: dict[str, Any] = field(default_factory=dict)
