"""Tests for Jinja2 template rendering."""

import pytest
from jinja2 import UndefinedError
from jinja2.exceptions import SecurityError

from penguin_email.templates.engine import TemplateRenderer


class TestTemplateRenderer:
    def setup_method(self) -> None:
        self.renderer = TemplateRenderer()

    # Built-in templates
    def test_welcome_renders(self) -> None:
        html = self.renderer.render_builtin(
            "welcome",
            name="Alice",
            app_name="TestApp",
            login_url="https://app.example.com/login",
        )
        assert "Alice" in html
        assert "TestApp" in html
        assert "https://app.example.com/login" in html

    def test_notification_renders(self) -> None:
        html = self.renderer.render_builtin(
            "notification",
            name="Bob",
            title="Your order shipped",
            body="It's on the way.",
            action_url="https://track.example.com",
            action_label="Track Order",
        )
        assert "Bob" in html
        assert "Your order shipped" in html

    def test_transactional_renders(self) -> None:
        html = self.renderer.render_builtin(
            "transactional",
            name="Carol",
            subject_detail="Invoice #1234",
            items=[
                {"description": "Widget A", "amount": "$9.99"},
                {"description": "Widget B", "amount": "$4.99"},
            ],
            total="$14.98",
        )
        assert "Carol" in html
        assert "Widget A" in html
        assert "$14.98" in html

    def test_alert_renders(self) -> None:
        html = self.renderer.render_builtin(
            "alert",
            name="Dave",
            severity="warning",
            message="Disk usage above 90%",
            timestamp="2025-01-01T12:00:00Z",
        )
        assert "warning" in html
        assert "Disk usage above 90%" in html

    def test_password_reset_renders(self) -> None:
        html = self.renderer.render_builtin(
            "password_reset",
            name="Eve",
            reset_url="https://example.com/reset/abc123",
            expires_in="1 hour",
        )
        assert "Eve" in html
        assert "https://example.com/reset/abc123" in html

    def test_form_renders_as_table(self) -> None:
        html = self.renderer.render_builtin(
            "form",
            title="Contact Form",
            data={"Name": "Frank", "Message": "Hello!"},
        )
        assert "Frank" in html
        assert "Hello!" in html
        assert "<table" in html

    def test_missing_required_variable_raises_undefined_error(self) -> None:
        with pytest.raises(UndefinedError):
            # name is required but not passed
            self.renderer.render_builtin("welcome", app_name="App", login_url="http://x")

    def test_template_file_loads_from_path(self, tmp_path) -> None:
        tpl = tmp_path / "custom.html.j2"
        tpl.write_text("<p>Hello {{ name }}!</p>")
        html = self.renderer.render_file(str(tpl), name="World")
        assert html == "<p>Hello World!</p>"

    def test_strip_tags_removes_html(self) -> None:
        result = self.renderer.strip_tags("<p>Hello <b>World</b>!</p>")
        assert "<" not in result
        assert "Hello" in result
        assert "World" in result

    def test_render_string(self) -> None:
        result = self.renderer.render_string("Hello {{ name }}!", name="Zara")
        assert result == "Hello Zara!"

    def test_render_string_autoescapes_by_default(self) -> None:
        result = self.renderer.render_string("Hello {{ name }}", name="A & B")
        assert result == "Hello A &amp; B"

    def test_render_string_autoescape_false_leaves_value_raw(self) -> None:
        result = self.renderer.render_string("Hello {{ name }}", name="A & B", autoescape=False)
        assert result == "Hello A & B"

    # SSTI sandboxing (regression: SandboxedEnvironment blocks Python-internals
    # attribute access on caller-supplied template text)
    def test_render_string_blocks_sandbox_escape_attribute_access(self) -> None:
        malicious = '{{ "".__class__.__mro__[1].__subclasses__() }}'
        with pytest.raises(SecurityError):
            self.renderer.render_string(malicious)

    def test_render_string_blocks_globals_access(self) -> None:
        malicious = "{{ range.__globals__ }}"
        with pytest.raises(SecurityError):
            self.renderer.render_string(malicious)

    def test_render_string_still_renders_legitimate_template(self) -> None:
        result = self.renderer.render_string("Hello {{ name }}!", name="Zara")
        assert result == "Hello Zara!"

    def test_render_file_blocks_sandbox_escape_attribute_access(self, tmp_path) -> None:
        tpl = tmp_path / "evil.html.j2"
        tpl.write_text("{{ [].__class__.__base__.__subclasses__() }}")
        with pytest.raises(SecurityError):
            self.renderer.render_file(str(tpl))

    def test_render_file_still_renders_legitimate_template(self, tmp_path) -> None:
        tpl = tmp_path / "custom.html.j2"
        tpl.write_text("<p>Hello {{ name }}!</p>")
        html = self.renderer.render_file(str(tpl), name="World")
        assert html == "<p>Hello World!</p>"

    def test_render_builtin_still_renders_after_sandboxing_string_paths(self) -> None:
        html = self.renderer.render_builtin(
            "welcome",
            name="Alice",
            app_name="TestApp",
            login_url="https://app.example.com/login",
        )
        assert "Alice" in html
