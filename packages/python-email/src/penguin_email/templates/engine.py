"""Jinja2-based template rendering engine."""

from __future__ import annotations

from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    PackageLoader,
    StrictUndefined,
    select_autoescape,
)


class TemplateRenderer:
    """Renders built-in or custom Jinja2 email templates.

    Built-in templates are loaded from the ``penguin_email/templates/builtin/``
    package directory using :mod:`importlib.resources` — this works correctly
    from an installed wheel, avoiding any ``pkg_resources`` dependency.
    """

    def __init__(self) -> None:
        # Environment for built-in templates (PackageLoader)
        self._builtin_env = Environment(
            loader=PackageLoader("penguin_email", "templates/builtin"),
            autoescape=select_autoescape(["html", "j2"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_builtin(self, template_name: str, **kwargs: object) -> str:
        """Render a built-in template by name.

        The ``.html.j2`` extension is added automatically if not present.

        Raises :exc:`jinja2.TemplateNotFound` if *template_name* does not match
        any built-in template.  Raises :exc:`jinja2.UndefinedError` if a
        required template variable is missing.
        """
        tpl = template_name if template_name.endswith(".html.j2") else f"{template_name}.html.j2"
        template = self._builtin_env.get_template(tpl)
        return template.render(**kwargs)

    def render_file(self, path: str, **kwargs: object) -> str:
        """Render a Jinja2 template from an arbitrary filesystem path."""
        p = Path(path)
        env = Environment(
            loader=FileSystemLoader(str(p.parent)),
            autoescape=select_autoescape(["html", "j2"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(p.name)
        return template.render(**kwargs)

    def render_string(self, template_str: str, **kwargs: object) -> str:
        """Render a raw Jinja2 string template."""
        env = Environment(
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.from_string(template_str)
        return template.render(**kwargs)

    def strip_tags(self, html: str) -> str:
        """Strip HTML tags to produce a plain-text fallback.

        Uses stdlib :mod:`html.parser` — no extra dependency.
        """
        from html.parser import HTMLParser

        class _Stripper(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data: str) -> None:
                self.parts.append(data)

        stripper = _Stripper()
        stripper.feed(html)
        return " ".join(stripper.parts).strip()
