"""KMS provider interface for wrapping/unwrapping tenant DEKs under a KEK.

Each provider instance is bound to one key reference (`kek_ref` in the
`tenant_encryption_keys` schema) at construction time, mirroring the design:
platform tenants get a fixed platform KMS key id, Enterprise/BYOK tenants
get a customer-owned KMS key reference. `LocalSecretKek` is the alpha/dev
provider (KEK sourced from a mounted secret file or env, never a hardcoded
value). Cloud KMS providers are implemented (`AwsKmsKek`) or explicitly
stubbed (`GcpKmsKek`, `AzureKeyVaultKek`, `VaultTransitKek`) — stubs raise
`NotImplementedError` at construction so a caller can never silently get a
no-op KEK that "wraps" a DEK without protecting it.

**Every wrap/unwrap call is bound to a `context` mapping** (must include
`tenant_id`) — this is the KEK-layer equivalent of the field-level AAD
(`aad.build_aad`): it stops a `wrapped_dek` row copied from one tenant into
another tenant's `tenant_encryption_keys` row from unwrapping successfully,
even if both rows happen to reference the same underlying KMS key. AWS KMS
enforces this natively via `EncryptionContext` (must match byte-for-byte
between `Encrypt`/`GenerateDataKey` and `Decrypt`, or KMS itself rejects the
call); `LocalSecretKek` binds the same context as AES-GCM AAD.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MIN_KEK_LENGTH = 32  # 256-bit minimum, matches the DEK/AES-256 key size
_LOCAL_NONCE_LEN = 12
_VALID_ENCODINGS = ("raw", "hex", "base64")
_REQUIRED_CONTEXT_KEY = "tenant_id"


def _require_tenant_context(context: Mapping[str, str]) -> None:
    """Every wrap/unwrap call must scope its context to a tenant.

    Raises:
        ValueError: If `context` is empty or missing the `tenant_id` key —
            an unscoped wrap/unwrap call defeats the whole point of binding
            context, so it is refused rather than silently allowed.
    """
    if not context.get(_REQUIRED_CONTEXT_KEY):
        raise ValueError(
            f"context must include a non-empty {_REQUIRED_CONTEXT_KEY!r} key "
            "(cross-tenant wrap/unwrap protection requires it)"
        )


def _encode_context(context: Mapping[str, str]) -> bytes:
    """Canonical, order-independent, length-prefixed encoding of a context mapping.

    Used as the AES-GCM AAD for `LocalSecretKek`. Sorted by key so dict
    iteration order never changes the resulting AAD, and each key/value is
    length-prefixed so no combination of keys/values can collide.

    Args:
        context: The wrap/unwrap context (e.g. `{"tenant_id": ..., "purpose": ...}`).

    Returns:
        Deterministic byte encoding of `context`.
    """
    parts: list[bytes] = []
    for key in sorted(context):
        for field in (key, context[key]):
            raw = field.encode("utf-8")
            parts.append(len(raw).to_bytes(4, "big"))
            parts.append(raw)
    return b"".join(parts)


class _KmsClient(Protocol):
    """Structural type for the subset of a boto3 KMS client `AwsKmsKek` calls.

    Avoids a hard dependency on `boto3`/`boto3-stubs` typings at import
    time while still giving mypy real signatures instead of `object`.
    """

    def encrypt(
        self,
        *,
        KeyId: str,  # noqa: N803
        Plaintext: bytes,  # noqa: N803
        EncryptionContext: Mapping[str, str],  # noqa: N803
    ) -> dict[str, Any]:
        """Match `boto3` KMS client's `encrypt` call shape (boto3's arg casing)."""
        ...

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,  # noqa: N803
        KeyId: str,  # noqa: N803
        EncryptionContext: Mapping[str, str],  # noqa: N803
    ) -> dict[str, Any]:
        """Match `boto3` KMS client's `decrypt` call shape (boto3's arg casing)."""
        ...

    def describe_key(self, *, KeyId: str) -> dict[str, Any]:  # noqa: N803
        """Match `boto3` KMS client's `describe_key` call shape (boto3's arg casing)."""
        ...


class KekProvider(Protocol):
    """Wraps/unwraps a single tenant DEK under one key-encryption key."""

    def wrap(self, dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Wrap (encrypt) a plaintext DEK, cryptographically bound to `context`."""
        ...

    def unwrap(self, wrapped_dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Unwrap a stored `wrapped_dek`; fails unless `context` matches the wrap call's."""
        ...


class LocalSecretKek:
    """KEK sourced from a mounted secret file or provided bytes — alpha/dev only.

    Never intended for production tenant isolation (there is no external
    KMS access-revocation boundary); the tenant-envelope-encryption design's
    production posture is platform KMS (baseline) or customer KMS (Enterprise
    BYOK). Refuses construction if the resolved key material is shorter than
    `_MIN_KEK_LENGTH` bytes, since a short KEK undermines the AES-256 wrap.
    """

    def __init__(
        self,
        *,
        key_material: bytes | None = None,
        key_path: str | os.PathLike[str] | None = None,
        env_var: str | None = None,
        encoding: str = "raw",
    ) -> None:
        """Resolve KEK bytes from exactly one of key_material, key_path, or env_var.

        Args:
            key_material: KEK bytes, already resolved by the caller (per
                `encoding`: raw key bytes, or ASCII hex/base64 text encoded
                as bytes).
            key_path: Path to a mounted secret file containing the KEK
                (e.g. a Kubernetes Secret volume mount).
            env_var: Name of an environment variable holding the KEK.
            encoding: How the resolved bytes encode the key — `"raw"`
                (default, used literally, sliced to 32 bytes), `"hex"`, or
                `"base64"`. **Must be set explicitly for encoded input** —
                there is no auto-detection, since guessing an encoding is
                exactly the ambiguity that causes silent truncation (a
                64-character hex string "looks" like a valid 64-byte raw
                key and would otherwise pass the length check while being
                sliced to 32 *characters* of hex text instead of the 32
                *decoded* key bytes it actually represents).

        Raises:
            ValueError: If zero or more than one source is given, if the
                file/env var is missing, if `encoding` is not one of
                `"raw"`/`"hex"`/`"base64"`, if hex/base64-declared input
                fails to decode, or if the resulting key material is
                shorter than 32 bytes.
        """
        if encoding not in _VALID_ENCODINGS:
            raise ValueError(f"encoding must be one of {_VALID_ENCODINGS}, got {encoding!r}")

        sources = [s for s in (key_material, key_path, env_var) if s is not None]
        if len(sources) != 1:
            raise ValueError("exactly one of key_material, key_path, or env_var is required")

        resolved: bytes
        if key_material is not None:
            resolved = key_material
        elif key_path is not None:
            path = Path(key_path)
            if not path.is_file():
                raise ValueError(f"KEK secret file not found: {path}")
            resolved = path.read_bytes().rstrip(b"\n")
        elif env_var is not None:
            value = os.environ.get(env_var)
            if value is None:
                raise ValueError(f"KEK environment variable not set: {env_var}")
            resolved = value.encode("utf-8")
        else:  # pragma: no cover - unreachable given the single-source check above
            raise ValueError("no KEK source resolved")

        resolved = _decode_kek_material(resolved, encoding)

        if len(resolved) < _MIN_KEK_LENGTH:
            raise ValueError(
                f"KEK material too short: {len(resolved)} bytes, need >= {_MIN_KEK_LENGTH}"
            )

        # Use exactly 32 bytes (AES-256) regardless of a longer supplied secret.
        self._kek = resolved[:32]

    def wrap(self, dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Wrap `dek` as `nonce(12B) || AESGCM(dek, aad=context)`.

        Args:
            dek: Plaintext DEK to wrap.
            context: Binding context (must include `tenant_id`) — encoded
                canonically via `_encode_context` and used as the AES-GCM AAD.

        Raises:
            ValueError: If `context` is missing `tenant_id`.
        """
        _require_tenant_context(context)
        nonce = os.urandom(_LOCAL_NONCE_LEN)
        ct = AESGCM(self._kek).encrypt(nonce, dek, _encode_context(context))
        return nonce + ct

    def unwrap(self, wrapped_dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Reverse `wrap` — fails unless `context` matches the wrap call's exactly.

        Raises:
            ValueError: If `context` is missing `tenant_id`, or if
                `wrapped_dek` is too short to contain a nonce and tag.
            cryptography.exceptions.InvalidTag: If `context` doesn't match
                what was used at wrap time (including a cross-tenant swap).
        """
        _require_tenant_context(context)
        if len(wrapped_dek) < _LOCAL_NONCE_LEN + 16:
            raise ValueError("wrapped_dek too short")
        nonce, ct = wrapped_dek[:_LOCAL_NONCE_LEN], wrapped_dek[_LOCAL_NONCE_LEN:]
        result: bytes = AESGCM(self._kek).decrypt(nonce, ct, _encode_context(context))
        return result


def _decode_kek_material(resolved: bytes, encoding: str) -> bytes:
    """Decode raw/hex/base64-declared KEK bytes, always before the length check.

    Raises:
        ValueError: If `encoding` is `"hex"`/`"base64"` and `resolved`
            isn't valid hex/base64 text.
    """
    if encoding == "raw":
        return resolved

    text = resolved.decode("ascii", errors="strict").strip()
    try:
        if encoding == "hex":
            return bytes.fromhex(text)
        return base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"KEK material is not valid {encoding}: {exc}") from exc


class AwsKmsKek:
    """AWS KMS-backed KEK — fully implemented (platform baseline or customer BYOK ARN).

    Requires the `aws` extra (`penguin-crypto[aws]`, i.e. `boto3`). The KMS
    client is never constructed eagerly at import time — only when this
    class is instantiated — so importing `penguin_crypto.envelope` never
    requires `boto3` to be installed.

    Resolves `key_id` (alias or ARN) to its canonical key ARN once at
    construction via `kms:DescribeKey`, so decrypt-time validation is
    correct regardless of whether `key_id` was given as an alias (KMS's
    `Decrypt` response always names the underlying key's ARN, never the
    alias used to invoke it — comparing the raw `key_id` against that
    response would spuriously fail for every alias-based key).
    """

    def __init__(
        self,
        key_id: str,
        *,
        client: _KmsClient | None = None,
        region_name: str | None = None,
    ) -> None:
        """Bind this provider to one KMS key (platform key id, alias, or customer ARN).

        Args:
            key_id: KMS key id, `alias/...` name, or ARN — the design's
                `kek_ref` column value.
            client: Pre-built `boto3` KMS client (mainly for tests); if
                omitted, one is constructed via `boto3.client("kms", ...)`.
            region_name: Passed through to `boto3.client` when `client` is
                not supplied.

        Raises:
            ImportError: If `boto3` is not installed and no `client` was supplied.
        """
        self.key_id = key_id
        self._client: _KmsClient
        if client is not None:
            self._client = client
        else:
            try:
                import boto3  # noqa: PLC0415 - intentionally lazy, see class docstring
            except ImportError as exc:  # pragma: no cover - exercised via missing-extra doc test
                raise ImportError(
                    "AwsKmsKek requires the 'aws' extra: pip install 'penguin-crypto[aws]'"
                ) from exc

            self._client = boto3.client("kms", region_name=region_name)

        # Resolve alias -> canonical key ARN once, so decrypt-response
        # validation works uniformly whether key_id is an alias or an ARN.
        self._canonical_key_arn: str = self._client.describe_key(KeyId=key_id)["KeyMetadata"]["Arn"]

    def wrap(self, dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Wrap `dek` via `kms:Encrypt` under `self.key_id`, bound to `context`.

        Args:
            dek: Plaintext DEK to wrap.
            context: Passed through as the KMS `EncryptionContext` (must
                include `tenant_id`) — KMS itself refuses to decrypt with a
                mismatched context, so this is enforced by the KMS service,
                not just by this client.

        Raises:
            ValueError: If `context` is missing `tenant_id`.
        """
        _require_tenant_context(context)
        response = self._client.encrypt(KeyId=self.key_id, Plaintext=dek, EncryptionContext=context)
        blob = response["CiphertextBlob"]
        if not isinstance(blob, bytes):
            raise TypeError(f"KMS encrypt returned a non-bytes CiphertextBlob: {type(blob)!r}")
        return blob

    def unwrap(self, wrapped_dek: bytes, *, context: Mapping[str, str]) -> bytes:
        """Unwrap `wrapped_dek` via `kms:Decrypt`, requiring the same `context` used to wrap.

        Also verifies the response's `KeyId` matches this provider's
        canonical key ARN, so a row's `wrapped_dek` can never be silently
        unwrapped under a different (e.g. another tenant's) KMS key than
        the one on record.

        Raises:
            ValueError: If `context` is missing `tenant_id`, or if the KMS
                response's KeyId doesn't match this provider's canonical ARN.
        """
        _require_tenant_context(context)
        response = self._client.decrypt(
            CiphertextBlob=wrapped_dek, KeyId=self.key_id, EncryptionContext=context
        )
        response_key_id = response.get("KeyId", "")
        if response_key_id != self._canonical_key_arn:
            raise ValueError(
                f"KMS decrypt returned a different key ({response_key_id!r}) than "
                f"expected ({self._canonical_key_arn!r})"
            )
        plaintext = response["Plaintext"]
        if not isinstance(plaintext, bytes):
            raise TypeError(f"KMS decrypt returned a non-bytes Plaintext: {type(plaintext)!r}")
        return plaintext


class GcpKmsKek:
    """GCP Cloud KMS-backed KEK — not yet implemented.

    Follow-up: wrap/unwrap via `google-cloud-kms`'s `encrypt`/`decrypt` RPCs
    against a `projects/*/locations/*/keyRings/*/cryptoKeys/*` resource
    name, using the RPC's `additional_authenticated_data` field for the
    same tenant-scoped context binding `AwsKmsKek`/`LocalSecretKek` provide.
    """

    def __init__(self, key_name: str) -> None:
        """Raise immediately — no silent no-op KEK is ever constructible.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "GcpKmsKek is not implemented yet; use AwsKmsKek or LocalSecretKek. "
            "Tracked as a documented follow-up in the envelope-encryption design."
        )


class AzureKeyVaultKek:
    """Azure Key Vault-backed KEK — not yet implemented.

    Follow-up: wrap/unwrap via the Key Vault Keys `wrapKey`/`unwrapKey` REST
    operations (`azure-keyvault-keys` SDK) against a vault key version. Key
    Vault's `wrapKey`/`unwrapKey` have no native AAD/context parameter, so
    the tenant-scoped context binding would need to be implemented as an
    envelope wrap (AES-GCM with `context` as AAD, as `LocalSecretKek` does)
    around the Key-Vault-wrapped bytes.
    """

    def __init__(self, vault_key_id: str) -> None:
        """Raise immediately — no silent no-op KEK is ever constructible.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "AzureKeyVaultKek is not implemented yet; use AwsKmsKek or LocalSecretKek. "
            "Tracked as a documented follow-up in the envelope-encryption design."
        )


class VaultTransitKek:
    """HashiCorp Vault Transit-backed KEK — not yet implemented.

    Follow-up: wrap/unwrap via Vault's Transit secrets engine
    `POST /v1/transit/encrypt/:key_name` / `.../decrypt/:key_name` endpoints
    (`hvac` client, passing `context` as Transit's `context` parameter,
    base64-encoded per Vault's API), returning Vault's `vault:v1:...`
    ciphertext envelope directly as the wrapped-DEK bytes.
    """

    def __init__(self, key_name: str) -> None:
        """Raise immediately — no silent no-op KEK is ever constructible.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "VaultTransitKek is not implemented yet; use AwsKmsKek or LocalSecretKek. "
            "Tracked as a documented follow-up in the envelope-encryption design."
        )


__all__ = [
    "KekProvider",
    "LocalSecretKek",
    "AwsKmsKek",
    "GcpKmsKek",
    "AzureKeyVaultKek",
    "VaultTransitKek",
]
