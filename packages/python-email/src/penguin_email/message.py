"""Fluent EmailMessage builder."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Attachment:
    """A file or byte-string attachment to include in an email."""

    filename: str
    content_type: str
    data: bytes | None = field(default=None)
    path: str | None = field(default=None)
    cid: str | None = field(default=None)  # set for inline images


class EmailMessage:
    """Fluent builder for constructing an email message.

    All mutating methods return ``self`` so calls can be chained::

        msg = (
            EmailMessage()
            .from_addr("sender@example.com")
            .to("alice@example.com")
            .subject("Hello!")
            .template("welcome", name="Alice", app_name="MyApp",
                       login_url="https://app.example.com")
        )
        client.send(msg)

    Call :meth:`build` explicitly (or let :class:`EmailClient` call it) to
    validate that all required fields are present before sending.
    """

    def __init__(self) -> None:
        self._from: str = ""
        self._to: list[str] = []
        self._cc: list[str] = []
        self._bcc: list[str] = []
        self._reply_to: str = ""
        self._subject: str = ""

        # Body sources — exactly one must be set before build()
        self._html_body: str = ""
        self._text_body: str = ""
        self._template_name: str = ""
        self._template_file: str = ""
        self._template_kwargs: dict[str, Any] = {}

        # Structured content helpers
        self._form_data: dict[str, str] | None = None
        self._table_headers: list[str] = []
        self._table_rows: list[list[Any]] = []
        self._table_caption: str = ""

        self._attachments: list[Attachment] = []
        self._built: bool = False

    # ------------------------------------------------------------------
    # Address helpers
    # ------------------------------------------------------------------

    def from_addr(self, addr: str) -> "EmailMessage":
        """Set the From address."""
        self._from = addr
        return self

    def to(self, *addrs: str) -> "EmailMessage":
        """Add one or more To recipients."""
        self._to.extend(addrs)
        return self

    def cc(self, *addrs: str) -> "EmailMessage":
        """Add one or more CC recipients."""
        self._cc.extend(addrs)
        return self

    def bcc(self, *addrs: str) -> "EmailMessage":
        """Add one or more BCC recipients."""
        self._bcc.extend(addrs)
        return self

    def reply_to(self, addr: str) -> "EmailMessage":
        """Set the Reply-To address."""
        self._reply_to = addr
        return self

    def subject(self, subject: str) -> "EmailMessage":
        """Set the email subject line."""
        self._subject = subject
        return self

    # ------------------------------------------------------------------
    # Body sources (exactly one required)
    # ------------------------------------------------------------------

    def html(self, html: str) -> "EmailMessage":
        """Set raw HTML body directly."""
        self._html_body = html
        return self

    def text(self, text: str) -> "EmailMessage":
        """Override the auto-generated plain-text body."""
        self._text_body = text
        return self

    def template(self, template_name: str, **kwargs: Any) -> "EmailMessage":
        """Use a built-in Jinja2 template by name.

        Available names: ``welcome``, ``notification``, ``transactional``,
        ``alert``, ``password_reset``, ``form``.
        """
        self._template_name = template_name
        self._template_kwargs = kwargs
        return self

    def template_file(self, path: str, **kwargs: Any) -> "EmailMessage":
        """Use a custom ``.html.j2`` template from the filesystem."""
        self._template_file = path
        self._template_kwargs = kwargs
        return self

    # ------------------------------------------------------------------
    # Structured content helpers
    # ------------------------------------------------------------------

    def form(self, data: dict[str, str]) -> "EmailMessage":
        """Render a two-column key/value form table.

        Raises :exc:`ValueError` if *data* is empty.
        """
        if not data:
            raise ValueError("form() requires at least one key/value pair")
        self._form_data = data
        return self

    def table(
        self,
        headers: list[str],
        rows: list[list[Any]],
        caption: str = "",
    ) -> "EmailMessage":
        """Embed an HTML table with *headers* and *rows*."""
        self._table_headers = headers
        self._table_rows = rows
        self._table_caption = caption
        return self

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def attach(self, path: str, filename: str = "") -> "EmailMessage":
        """Attach a file from the filesystem."""
        p = Path(path)
        fn = filename or p.name
        ct, _ = mimetypes.guess_type(path)
        self._attachments.append(
            Attachment(filename=fn, content_type=ct or "application/octet-stream", path=path)
        )
        return self

    def attach_bytes(
        self,
        data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> "EmailMessage":
        """Attach raw bytes."""
        self._attachments.append(
            Attachment(filename=filename, content_type=content_type, data=data)
        )
        return self

    def inline_image(self, path: str, cid: str) -> "EmailMessage":
        """Attach an image as an inline resource referenced by ``cid``."""
        p = Path(path)
        ct, _ = mimetypes.guess_type(path)
        self._attachments.append(
            Attachment(
                filename=p.name,
                content_type=ct or "image/png",
                path=path,
                cid=cid,
            )
        )
        return self

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def build(self) -> "EmailMessage":
        """Validate the message and mark it as ready to send.

        Raises :exc:`ValueError` if:
        - No ``to`` recipients have been added.
        - No ``subject`` has been set.
        - More than one body source is specified.
        - No body source is specified (and no ``.form()`` data is present).
        """
        if not self._to:
            raise ValueError("At least one 'to' recipient is required")
        if not self._subject:
            raise ValueError("'subject' is required")

        body_sources = sum(
            bool(x)
            for x in [
                self._html_body,
                self._template_name,
                self._template_file,
                self._form_data,
            ]
        )
        if body_sources > 1:
            raise ValueError(
                "Specify exactly one body source: html(), template(), "
                "template_file(), or form()"
            )
        if body_sources == 0:
            raise ValueError(
                "A body source is required: html(), template(), "
                "template_file(), or form()"
            )

        self._built = True
        return self

    # ------------------------------------------------------------------
    # Read-only accessors (used by transports and the client)
    # ------------------------------------------------------------------

    @property
    def sender(self) -> str:
        return self._from

    @property
    def recipients(self) -> list[str]:
        return list(self._to)

    @property
    def cc_recipients(self) -> list[str]:
        return list(self._cc)

    @property
    def bcc_recipients(self) -> list[str]:
        return list(self._bcc)

    @property
    def reply_to_addr(self) -> str:
        return self._reply_to

    @property
    def subject_line(self) -> str:
        return self._subject

    @property
    def html_body(self) -> str:
        return self._html_body

    @property
    def text_body(self) -> str:
        return self._text_body

    @property
    def template_name(self) -> str:
        return self._template_name

    @property
    def template_path(self) -> str:
        return self._template_file

    @property
    def template_kwargs(self) -> dict[str, Any]:
        return dict(self._template_kwargs)

    @property
    def form_data(self) -> dict[str, str] | None:
        return dict(self._form_data) if self._form_data is not None else None

    @property
    def table_headers(self) -> list[str]:
        return list(self._table_headers)

    @property
    def table_rows(self) -> list[list[Any]]:
        return [list(row) for row in self._table_rows]

    @property
    def table_caption(self) -> str:
        return self._table_caption

    @property
    def attachments(self) -> list[Attachment]:
        return list(self._attachments)

    @property
    def is_built(self) -> bool:
        return self._built
