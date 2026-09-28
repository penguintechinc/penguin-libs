"""Tests for KEK providers: LocalSecretKek, AwsKmsKek, and the documented stubs."""

import base64
import os
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from penguin_crypto.envelope.kek import (
    AwsKmsKek,
    AzureKeyVaultKek,
    GcpKmsKek,
    LocalSecretKek,
    VaultTransitKek,
)

_CTX = {"tenant_id": "tenant-a", "purpose": "field-dek"}
_OTHER_TENANT_CTX = {"tenant_id": "tenant-b", "purpose": "field-dek"}


class _FakeKmsClient:
    """Minimal stand-in matching the `_KmsClient` structural protocol, no network calls."""

    def __init__(
        self, *, canonical_arn: str = "arn:aws:kms:us-east-1:1234:key/real-key-id"
    ) -> None:
        self.key = os.urandom(32)
        self.calls: list[str] = []
        self.canonical_arn = canonical_arn
        self.last_encrypt_context: dict[str, str] | None = None

    def describe_key(self, *, KeyId: str) -> dict[str, object]:  # noqa: N803
        """Fake KMS describe_key — always resolves to `self.canonical_arn`, alias or not."""
        self.calls.append("describe_key")
        return {"KeyMetadata": {"Arn": self.canonical_arn}}

    def encrypt(
        self,
        *,
        KeyId: str,  # noqa: N803
        Plaintext: bytes,  # noqa: N803
        EncryptionContext: dict[str, str],  # noqa: N803
    ) -> dict[str, object]:
        """Fake KMS encrypt — XORs with a fixed key; records the context for `decrypt`.

        Real KMS enforces `EncryptionContext` server-side; this fake records
        what was passed at encrypt time and checks it again in `decrypt`
        below to simulate that enforcement.
        """
        self.calls.append("encrypt")
        self.last_encrypt_context = dict(EncryptionContext)
        blob = bytes(a ^ b for a, b in zip(Plaintext, self.key * 4, strict=False))
        return {"CiphertextBlob": blob}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,  # noqa: N803
        KeyId: str,  # noqa: N803
        EncryptionContext: dict[str, str],  # noqa: N803
    ) -> dict[str, object]:
        """Fake KMS decrypt — reverses `encrypt`, echoes the canonical ARN as KeyId.

        Simulates KMS's context enforcement: rejects if the context doesn't
        match what was passed to `encrypt`.
        """
        self.calls.append("decrypt")
        if dict(EncryptionContext) != self.last_encrypt_context:
            raise ValueError("simulated KMS InvalidCiphertextException: context mismatch")
        plaintext = bytes(a ^ b for a, b in zip(CiphertextBlob, self.key * 4, strict=False))
        return {"Plaintext": plaintext, "KeyId": self.canonical_arn}


# --- LocalSecretKek -----------------------------------------------------------------


def test_local_secret_kek_round_trip_with_key_material() -> None:
    """wrap() then unwrap() with an in-memory KEK returns the original DEK."""
    kek = LocalSecretKek(key_material=os.urandom(32))
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek, context=_CTX), context=_CTX) == dek


def test_local_secret_kek_round_trip_with_key_path(tmp_path: Path) -> None:
    """A KEK sourced from a mounted secret file works identically to raw bytes."""
    key_file = tmp_path / "kek.bin"
    key_file.write_bytes(os.urandom(32))

    kek = LocalSecretKek(key_path=key_file)
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek, context=_CTX), context=_CTX) == dek


def test_local_secret_kek_round_trip_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """A KEK sourced from an environment variable works identically to raw bytes."""
    monkeypatch.setenv("TEST_KEK", "x" * 32)
    kek = LocalSecretKek(env_var="TEST_KEK")
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek, context=_CTX), context=_CTX) == dek


def test_local_secret_kek_round_trip_with_hex_encoding() -> None:
    """A hex-declared KEK is decoded to raw bytes before use, not truncated as ASCII text."""
    raw_key = os.urandom(32)
    kek_hex = LocalSecretKek(key_material=raw_key.hex().encode("ascii"), encoding="hex")
    kek_raw = LocalSecretKek(key_material=raw_key)

    dek = os.urandom(32)
    wrapped = kek_raw.wrap(dek, context=_CTX)
    # Same underlying 32-byte key material as constructing directly from raw bytes.
    assert kek_hex.unwrap(wrapped, context=_CTX) == dek


def test_local_secret_kek_round_trip_with_base64_encoding() -> None:
    """A base64-declared KEK is decoded to raw bytes before use."""
    raw_key = os.urandom(32)
    encoded = base64.b64encode(raw_key)
    kek = LocalSecretKek(key_material=encoded, encoding="base64")
    dek = os.urandom(32)
    assert kek.unwrap(kek.wrap(dek, context=_CTX), context=_CTX) == dek


def test_local_secret_kek_hex_encoding_without_decoding_would_silently_truncate() -> None:
    """Regression: a 64-hex-char key must NOT be silently sliced to 32 raw ASCII bytes.

    Demonstrates the bug this fix closes — decoding the same hex text as
    "raw" (the default, a caller bug if the material was actually hex)
    produces a materially different key than decoding it as hex, so the two
    providers must NOT be interoperable.
    """
    raw_key = os.urandom(32)
    hex_text = raw_key.hex().encode("ascii")  # 64 ASCII bytes

    kek_hex = LocalSecretKek(key_material=hex_text, encoding="hex")
    kek_raw_misuse = LocalSecretKek(key_material=hex_text)  # encoding="raw" (default) - a bug

    dek = os.urandom(32)
    wrapped = kek_hex.wrap(dek, context=_CTX)
    with pytest.raises(InvalidTag):
        kek_raw_misuse.unwrap(wrapped, context=_CTX)


def test_local_secret_kek_rejects_invalid_hex() -> None:
    """Malformed hex-declared input fails loudly rather than truncating or guessing."""
    with pytest.raises(ValueError, match="not valid hex"):
        LocalSecretKek(key_material=b"not-hex-at-all!!", encoding="hex")


def test_local_secret_kek_rejects_invalid_base64() -> None:
    """Malformed base64-declared input fails loudly rather than truncating or guessing."""
    with pytest.raises(ValueError, match="not valid base64"):
        LocalSecretKek(key_material=b"!!!not-base64!!!", encoding="base64")


def test_local_secret_kek_rejects_invalid_encoding_name() -> None:
    """An unrecognized `encoding` value is a caller configuration bug."""
    with pytest.raises(ValueError, match="encoding must be one of"):
        LocalSecretKek(key_material=os.urandom(32), encoding="rot13")


def test_local_secret_kek_refuses_short_key_material() -> None:
    """A KEK shorter than 32 bytes undermines the AES-256 wrap and must be refused."""
    with pytest.raises(ValueError, match="too short"):
        LocalSecretKek(key_material=b"short")


def test_local_secret_kek_refuses_short_key_after_hex_decode() -> None:
    """The length check happens on decoded bytes, not on the pre-decode encoded length."""
    short_key_hex = os.urandom(8).hex().encode("ascii")  # decodes to only 8 bytes
    with pytest.raises(ValueError, match="too short"):
        LocalSecretKek(key_material=short_key_hex, encoding="hex")


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
        kek.unwrap(b"short", context=_CTX)


def test_local_secret_kek_requires_tenant_id_in_context() -> None:
    """wrap()/unwrap() refuse a context missing tenant_id — never an unscoped wrap."""
    kek = LocalSecretKek(key_material=os.urandom(32))
    with pytest.raises(ValueError, match="tenant_id"):
        kek.wrap(os.urandom(32), context={"purpose": "x"})
    with pytest.raises(ValueError, match="tenant_id"):
        kek.unwrap(os.urandom(32), context={})


def test_local_secret_kek_cross_tenant_context_swap_is_rejected() -> None:
    """A wrapped_dek row copied to another tenant's context fails to unwrap.

    This is the KEK-layer equivalent of the field-level cross-tenant AAD
    swap test in test_cipher.py — the context is bound as AES-GCM AAD.
    """
    kek = LocalSecretKek(key_material=os.urandom(32))
    dek = os.urandom(32)
    wrapped = kek.wrap(dek, context=_CTX)
    with pytest.raises(InvalidTag):
        kek.unwrap(wrapped, context=_OTHER_TENANT_CTX)


def test_local_secret_kek_context_key_order_does_not_affect_binding() -> None:
    """Context is encoded canonically (sorted), so dict key order never matters."""
    kek = LocalSecretKek(key_material=os.urandom(32))
    dek = os.urandom(32)
    ctx_a = {"tenant_id": "t1", "purpose": "p1"}
    ctx_b = {"purpose": "p1", "tenant_id": "t1"}
    wrapped = kek.wrap(dek, context=ctx_a)
    assert kek.unwrap(wrapped, context=ctx_b) == dek


# --- AwsKmsKek ------------------------------------------------------------------------


def test_aws_kms_kek_round_trip_with_injected_client() -> None:
    """wrap()/unwrap() delegate to the injected KMS client and round-trip correctly."""
    client = _FakeKmsClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)

    dek = os.urandom(32)
    wrapped = kek.wrap(dek, context=_CTX)
    assert kek.unwrap(wrapped, context=_CTX) == dek
    assert client.calls == ["describe_key", "encrypt", "decrypt"]


def test_aws_kms_kek_resolves_alias_to_canonical_arn_at_construction() -> None:
    """Constructing with an alias resolves + stores the canonical key ARN via DescribeKey."""
    client = _FakeKmsClient(canonical_arn="arn:aws:kms:us-east-1:1234:key/real-key-id")
    kek = AwsKmsKek("alias/my-key", client=client)
    assert kek._canonical_key_arn == "arn:aws:kms:us-east-1:1234:key/real-key-id"  # noqa: SLF001


def test_aws_kms_kek_unwrap_succeeds_for_alias_constructed_provider() -> None:
    """An alias-constructed provider still validates decrypt correctly (regression).

    Before resolving aliases to their canonical ARN, comparing the raw
    `key_id` ("alias/my-key") against KMS's Decrypt response (which always
    names the real key ARN, never the alias) would spuriously fail here.
    """
    client = _FakeKmsClient(canonical_arn="arn:aws:kms:us-east-1:1234:key/real-key-id")
    kek = AwsKmsKek("alias/my-key", client=client)

    dek = os.urandom(32)
    wrapped = kek.wrap(dek, context=_CTX)
    assert kek.unwrap(wrapped, context=_CTX) == dek


def test_aws_kms_kek_context_is_passed_to_kms_encrypt() -> None:
    """The `context` mapping is forwarded as KMS's `EncryptionContext`."""
    client = _FakeKmsClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)

    kek.wrap(os.urandom(32), context=_CTX)
    assert client.last_encrypt_context == _CTX


def test_aws_kms_kek_rejects_mismatched_response_key_id() -> None:
    """A KMS decrypt response naming a different key than expected is never trusted."""

    class _WrongKeyClient(_FakeKmsClient):
        def decrypt(
            self,
            *,
            CiphertextBlob: bytes,  # noqa: N803
            KeyId: str,  # noqa: N803
            EncryptionContext: dict[str, str],  # noqa: N803
        ) -> dict[str, object]:
            result = super().decrypt(
                CiphertextBlob=CiphertextBlob, KeyId=KeyId, EncryptionContext=EncryptionContext
            )
            result["KeyId"] = "arn:aws:kms:us-east-1:1234:key/some-other-key"
            return result

    client = _WrongKeyClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)
    wrapped = kek.wrap(os.urandom(32), context=_CTX)

    with pytest.raises(ValueError, match="different key"):
        kek.unwrap(wrapped, context=_CTX)


def test_aws_kms_kek_requires_tenant_id_in_context() -> None:
    """wrap()/unwrap() refuse an unscoped context before ever calling KMS."""
    client = _FakeKmsClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)

    with pytest.raises(ValueError, match="tenant_id"):
        kek.wrap(os.urandom(32), context={})

    assert "encrypt" not in client.calls  # refused before touching KMS


def test_aws_kms_kek_cross_tenant_context_is_rejected_by_kms() -> None:
    """A wrapped_dek moved to another tenant's context fails at the (simulated) KMS layer."""
    client = _FakeKmsClient()
    kek = AwsKmsKek("arn:aws:kms:us-east-1:1234:key/abc", client=client)

    wrapped = kek.wrap(os.urandom(32), context=_CTX)
    with pytest.raises(ValueError, match="context mismatch"):
        kek.unwrap(wrapped, context=_OTHER_TENANT_CTX)


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
