"""Tests for EmailMessage fluent builder."""

import pytest

from penguin_email.message import EmailMessage


class TestEmailMessageBuilder:
    def test_fluent_chain_builds_correctly(self) -> None:
        msg = (
            EmailMessage()
            .from_addr("sender@example.com")
            .to("alice@example.com")
            .cc("bob@example.com")
            .bcc("carol@example.com")
            .reply_to("noreply@example.com")
            .subject("Test Subject")
            .html("<p>Hello</p>")
        )
        assert msg.sender == "sender@example.com"
        assert msg.recipients == ["alice@example.com"]
        assert msg.cc_recipients == ["bob@example.com"]
        assert msg.bcc_recipients == ["carol@example.com"]
        assert msg.reply_to_addr == "noreply@example.com"
        assert msg.subject_line == "Test Subject"
        assert msg.html_body == "<p>Hello</p>"

    def test_build_raises_if_no_to(self) -> None:
        msg = EmailMessage().subject("Hi").html("<p>Hi</p>")
        with pytest.raises(ValueError, match="recipient"):
            msg.build()

    def test_build_raises_if_no_subject(self) -> None:
        msg = EmailMessage().to("alice@example.com").html("<p>Hi</p>")
        with pytest.raises(ValueError, match="subject"):
            msg.build()

    def test_build_raises_if_empty_form(self) -> None:
        with pytest.raises(ValueError, match="form"):
            EmailMessage().form({})

    def test_form_stores_data_correctly(self) -> None:
        data = {"Name": "Alice", "Email": "alice@example.com"}
        msg = EmailMessage().to("r@example.com").subject("S").form(data)
        assert msg.form_data == data

    def test_table_stores_headers_and_rows(self) -> None:
        headers = ["Col A", "Col B"]
        rows = [["r1c1", "r1c2"], ["r2c1", "r2c2"]]
        msg = (
            EmailMessage()
            .to("r@example.com")
            .subject("S")
            .html("<p>body</p>")
            .table(headers, rows, caption="My Table")
        )
        assert msg.table_headers == headers
        assert msg.table_rows == rows
        assert msg.table_caption == "My Table"

    def test_multiple_to_calls_accumulate_addresses(self) -> None:
        msg = (
            EmailMessage()
            .to("a@example.com")
            .to("b@example.com", "c@example.com")
        )
        assert msg.recipients == ["a@example.com", "b@example.com", "c@example.com"]

    def test_build_raises_multiple_body_sources(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            (
                EmailMessage()
                .to("a@example.com")
                .subject("S")
                .html("<p>HTML</p>")
                .template("welcome", name="Alice", app_name="App", login_url="http://x")
            ).build()

    def test_build_raises_no_body_source(self) -> None:
        with pytest.raises(ValueError, match="body source"):
            EmailMessage().to("a@example.com").subject("S").build()

    def test_attach_file_stores_attachment(self, tmp_path) -> None:
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4")
        msg = (
            EmailMessage()
            .to("a@example.com")
            .subject("S")
            .html("<p>Hi</p>")
            .attach(str(f))
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == "doc.pdf"

    def test_attach_bytes_stores_attachment(self) -> None:
        msg = (
            EmailMessage()
            .to("a@example.com")
            .subject("S")
            .html("<p>Hi</p>")
            .attach_bytes(b"hello", "file.txt", "text/plain")
        )
        assert msg.attachments[0].data == b"hello"
        assert msg.attachments[0].filename == "file.txt"

    def test_inline_image_sets_cid(self, tmp_path) -> None:
        img = tmp_path / "logo.png"
        img.write_bytes(b"\x89PNG\r\n")
        msg = (
            EmailMessage()
            .to("a@example.com")
            .subject("S")
            .html("<p>Hi</p>")
            .inline_image(str(img), cid="logo")
        )
        assert msg.attachments[0].cid == "logo"

    def test_build_sets_built_flag(self) -> None:
        msg = EmailMessage().to("a@example.com").subject("S").html("<p>x</p>")
        assert not msg.is_built
        msg.build()
        assert msg.is_built

    def test_text_override_stored(self) -> None:
        msg = (
            EmailMessage()
            .to("a@example.com")
            .subject("S")
            .html("<p>Hi</p>")
            .text("Hi plain")
        )
        assert msg.text_body == "Hi plain"
