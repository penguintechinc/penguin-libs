"""Tests for KEK providers: LocalSecretKek, AwsKmsKek, and the documented stubs."""

import os

import pytest

from penguin_crypto.envelope.kek import (
    AwsKmsKek,
    AzureKeyVaultKek,
    GcpKmsKek,
    LocalSecretKek,
    VaultTransitKek,
)


class _FakeKmsClient:
    """Minimal stand-in matching the `_KmsClient` structural protocol, no network calls."""

    def __init__(self) -> None:
        self.key = os.urandom(32)
        self.calls: list[str] = []

    def encrypt(self, *, KeyId: str, Plaintext: bytes) -> dict[str, bytes]:  # noqa: N803
        """Fake KMS encrypt — XORs with a fixed key, just enough to prove wiring."""
        self.calls.append("encrypt")
        return {
            "CiphertextBlob": bytes(a ^ b for a, b in zip(Plaintext, self.key * 4, strict=False))
        }

    def decrypt(self, *, CiphertextBlob: bytes, KeyId: str) -> dict[str, bytes | str]:  # noqa: N803
        """Fake KMS decrypt — reverses `encrypt` and echoes back the requested KeyId."""
        self.calls.append("decrypt")
        plaintext = bytes(a ^ b for a, b in zip(CiphertextBlob, self.key * 4, strict=False))
        return {"Plaintext": plaintext, "KeyId": KeyId}


# --- LocalSecretKek -----------------------------------------------------------------


def test_local_secret_kek_round_trip_with_key_material() -> None:
    """wrap() then unwrap() with an in-memory KEK returns the original DEK."""
    kek = LocalSecretKek(key_material=os.urandom(32))
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek)) == dek


def test_local_secret_kek_round_trip_with_key_path(tmp_path: object) -> None:
    """A KEK sourced from a mounted secret file works identically to raw bytes."""
    from pathlib import Path

    key_file = Path(str(tmp_path)) / "kek.bin"
    key_file.write_bytes(os.urandom(32))

    kek = LocalSecretKek(key_path=key_file)
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek)) == dek


def test_local_secret_kek_round_trip_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """A KEK sourced from an environment variable works identically to raw bytes."""
    monkeypatch.setenv("TEST_KEK", "x" * 32)
    kek = LocalSecretKek(env_var="TEST_KEK")
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek)) == dek


def test_local_secret_kek_refuses_short_key_material() -> None:
    """A KEK shorter than 32 bytes undermines the AES-256 wrap and must be refused."""
    with pytest.raises(ValueError, match="too short"):
        LocalSecretKek(key_material=b"short")


def test_local_secret_kek_requires_exactly_one_source() -> None:
    """Zero or multiple sources is always a caller configuration bug."""
    with pytest.raises(ValueError, match="exactly one"):
        LocalSecretKek()

    with pytest.raises(ValueError, match="exactly one"):
        LocalSecretKek(key_material=os.urandom(32), env_var="X")


def test_local_secret_kek_missing_file_raises() -> None:
    """A configured but nonexistent secret file path fails loudly at construction."""
    with pytest.raises(ValueError, match="not found"):
        LocalSecretKek(key_path="/nonexistent/path/to/kek")


def test_local_secret_kek_missing_env_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured but unset env var fails loudly at construction."""
    monkeypatch.delenv("TEST_KEK_MISSING", raising=False)
    with pytest.raises(ValueError, match="not set"):
        LocalSecretKek(env_var="TEST_KEK_MISSING")


def test_local_secret_kek_unwrap_rejects_truncated_input() -> None:
    """A too-short wrapped blob can't possibly contain a nonce+tag."""
    kek = LocalSecretKek(key_material=os.urandom(32))
    with pytest.raises(ValueError, match="too short"):
        kek.unwrap(b"short")


# --- AwsKmsKek ------------------------------------------------------------------------


def test_aws_kms_kek_round_trip_with_injected_client() -> None:
    """wrap()/unwrap() delegate to the injected KMS client and round-trip correctly."""
    client = _FakeKmsClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)

    dek = os.urandom(32)
    wrapped = kek.wrap(dek)
    assert kek.unwrap(wrapped) == dek
    assert client.calls == ["encrypt", "decrypt"]


def test_aws_kms_kek_rejects_mismatched_response_key_id() -> None:
    """A KMS decrypt response naming a different key than expected is never trusted."""

    class _WrongKeyClient(_FakeKmsClient):
        def decrypt(self, *, CiphertextBlob: bytes, KeyId: str) -> dict[str, bytes | str]:  # noqa: N803
            result = super().decrypt(CiphertextBlob=CiphertextBlob, KeyId=KeyId)
            result["KeyId"] = "arn:aws:kms:us-east-1:1234:key/some-other-key"
            return result

    client = _WrongKeyClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)
    wrapped = kek.wrap(os.urandom(32))

    with pytest.raises(ValueError, match="different key"):
        kek.unwrap(wrapped)


def test_aws_kms_kek_requires_boto3_when_no_client_injected() -> None:
    """Without the `aws` extra installed (no client, no boto3), construction fails loudly.

    boto3 is present in this project's dev/test environment, so this test
    simulates the missing-dependency path by removing the module from
    sys.modules and blocking the import.
    """
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "boto3":
            raise ImportError("simulated missing boto3")
        return real_import(name, *args, **kwargs)

    sys.modules.pop("boto3", None)
    builtins.__import__ = _blocked_import
    try:
        with pytest.raises(ImportError, match="aws.*extra"):
            AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc")
    finally:
        builtins.__import__ = real_import


# --- Documented stubs (must never silently no-op) --------------------------------------


@pytest.mark.parametrize("provider_cls", [GcpKmsKek, AzureKeyVaultKek, VaultTransitKek])
def test_unimplemented_providers_raise_at_construction(provider_cls: type) -> None:
    """Unimplemented cloud KMS providers refuse construction rather than acting as a no-op KEK."""
    with pytest.raises(NotImplementedError):
        provider_cls("some-key-reference")
