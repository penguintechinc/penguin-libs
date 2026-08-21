"""Tests for DkimConfig and DkimSigner.

Uses an ephemeral RSA key generated at runtime via ``cryptography`` (already
pulled in transitively through the ``google-auth`` dev/gmail extra) -- no key
material is ever written to the repo, only to pytest's ``tmp_path``.
"""

from __future__ import annotations

from email.mime.text import MIMEText
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from penguin_email.dkim_signing import DkimConfig, DkimSigner, DkimSigningError
from penguin_email.transports.smtp import SmtpTransport


def _generate_pem_private_key() -> str:
    """Generate a throwaway RSA private key in memory; never persisted."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("ascii")


def _make_mime_bytes(subject: str = "Test") -> bytes:
    msg = MIMEText("hello world", "plain", "utf-8")
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = subject
    return msg.as_bytes()


@pytest.fixture(scope="module")
def dkim_private_key() -> str:
    return _generate_pem_private_key()


class TestDkimConfigFromEnv:
    def test_reads_default_var_names(self, monkeypatch, dkim_private_key) -> None:
        monkeypatch.setenv("DKIM_DOMAIN", "example.com")
        monkeypatch.setenv("DKIM_SELECTOR", "sel1")
        monkeypatch.setenv("DKIM_PRIVATE_KEY", dkim_private_key)

        config = DkimConfig.from_env()

        assert config.domain == "example.com"
        assert config.selector == "sel1"
        assert config.private_key == dkim_private_key

    def test_reads_custom_var_names(self, monkeypatch, dkim_private_key) -> None:
        monkeypatch.setenv("MY_DOMAIN", "custom.com")
        monkeypatch.setenv("MY_SELECTOR", "sel2")
        monkeypatch.setenv("MY_KEY", dkim_private_key)

        config = DkimConfig.from_env(
            domain_var="MY_DOMAIN", selector_var="MY_SELECTOR", private_key_var="MY_KEY"
        )

        assert config.domain == "custom.com"
        assert config.selector == "sel2"

    def test_missing_var_raises_key_error(self, monkeypatch) -> None:
        monkeypatch.delenv("DKIM_DOMAIN", raising=False)
        monkeypatch.delenv("DKIM_SELECTOR", raising=False)
        monkeypatch.delenv("DKIM_PRIVATE_KEY", raising=False)

        with pytest.raises(KeyError):
            DkimConfig.from_env()


class TestDkimConfigFromFile:
    def test_reads_key_from_path(self, tmp_path, dkim_private_key) -> None:
        key_path = tmp_path / "dkim_private.pem"
        key_path.write_text(dkim_private_key, encoding="utf-8")

        config = DkimConfig.from_file(
            domain="example.com", selector="sel1", private_key_path=str(key_path)
        )

        assert config.domain == "example.com"
        assert config.selector == "sel1"
        assert config.private_key == dkim_private_key


class TestDkimConfigKeyNeverLeaks:
    """The raw private key must never appear in repr()/str() of the config."""

    def test_repr_redacts_private_key(self, dkim_private_key) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        assert dkim_private_key not in repr(config)
        assert "redacted" in repr(config)

    def test_str_redacts_private_key(self, dkim_private_key) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        assert dkim_private_key not in str(config)


class TestDkimSignerImportGuard:
    def test_raises_import_error_when_dkimpy_missing(self, dkim_private_key) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        with patch("penguin_email.dkim_signing._dkimpy", None):
            with pytest.raises(ImportError, match="dkim"):
                DkimSigner(config)

    def test_smtp_transport_fails_fast_when_dkimpy_missing(self, dkim_private_key) -> None:
        """A missing [dkim] extra must raise at SmtpTransport(), not at send()."""
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        with patch("penguin_email.dkim_signing._dkimpy", None):
            with pytest.raises(ImportError):
                SmtpTransport(host="smtp.example.com", dkim=config)


class TestDkimSignerSign:
    def test_sign_prepends_dkim_signature_header(self, dkim_private_key) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        signer = DkimSigner(config)

        signed = signer.sign(_make_mime_bytes())

        assert signed.startswith(b"DKIM-Signature:")
        assert b"d=example.com" in signed
        assert b"s=sel1" in signed

    def test_sign_preserves_original_message_bytes_unmodified(self, dkim_private_key) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        signer = DkimSigner(config)
        original = _make_mime_bytes()

        signed = signer.sign(original)

        assert signed.endswith(original)

    def test_sign_raises_dkim_signing_error_on_malformed_key(self) -> None:
        config = DkimConfig(domain="example.com", selector="sel1", private_key="not-a-valid-key")
        signer = DkimSigner(config)

        with pytest.raises(DkimSigningError):
            signer.sign(_make_mime_bytes())

    def test_malformed_key_text_never_appears_in_raised_error(self) -> None:
        bogus_key = "-----BEGIN RSA PRIVATE KEY-----\nnot-actually-valid-material\n-----END-----"
        config = DkimConfig(domain="example.com", selector="sel1", private_key=bogus_key)
        signer = DkimSigner(config)

        with pytest.raises(DkimSigningError) as exc_info:
            signer.sign(_make_mime_bytes())

        assert bogus_key not in str(exc_info.value)
        assert "not-actually-valid-material" not in str(exc_info.value)

    def test_error_message_strips_underlying_exception_text_even_if_it_names_the_key(
        self, dkim_private_key
    ) -> None:
        """DkimSigner must never forward str(exc) from the wrapped library --
        only a fixed, key-free summary -- even in the worst case where the
        underlying library's own exception text happens to echo the key.
        """
        config = DkimConfig(domain="example.com", selector="sel1", private_key=dkim_private_key)
        signer = DkimSigner(config)

        with patch(
            "penguin_email.dkim_signing._dkimpy.sign",
            side_effect=RuntimeError(f"internal failure, key was: {dkim_private_key}"),
        ):
            with pytest.raises(DkimSigningError) as exc_info:
                signer.sign(_make_mime_bytes())

        assert dkim_private_key not in str(exc_info.value)
