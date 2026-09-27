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
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MIN_KEK_LENGTH = 32  # 256-bit minimum, matches the DEK/AES-256 key size
_LOCAL_NONCE_LEN = 12


class _KmsClient(Protocol):
    """Structural type for the subset of a boto3 KMS client `AwsKmsKek` calls.

    Avoids a hard dependency on `boto3`/`boto3-stubs` typings at import
    time while still giving mypy real signatures instead of `object`.
    """

    def encrypt(self, *, KeyId: str, Plaintext: bytes) -> dict[str, bytes]:  # noqa: N803
        """Match `boto3` KMS client's `encrypt` call shape (boto3's arg casing)."""
        ...

    def decrypt(self, *, CiphertextBlob: bytes, KeyId: str) -> dict[str, bytes | str]:  # noqa: N803
        """Match `boto3` KMS client's `decrypt` call shape (boto3's arg casing)."""
        ...


class KekProvider(Protocol):
    """Wraps/unwraps a single tenant DEK under one key-encryption key."""

    def wrap(self, dek: bytes) -> bytes:
        """Wrap (encrypt) a plaintext DEK for storage as `tenant_encryption_keys.wrapped_dek`."""
        ...

    def unwrap(self, wrapped_dek: bytes) -> bytes:
        """Unwrap (decrypt) a stored `wrapped_dek` back to the plaintext DEK."""
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
    ) -> None:
        """Resolve KEK bytes from exactly one of key_material, key_path, or env_var.

        Args:
            key_material: Raw KEK bytes, already resolved by the caller.
            key_path: Path to a mounted secret file containing the KEK
                (e.g. a Kubernetes Secret volume mount).
            env_var: Name of an environment variable holding the KEK,
                base64/hex not assumed — read as raw UTF-8-decoded bytes
                is the caller's responsibility if encoding is used;
                by default the raw string is encoded as UTF-8 bytes.

        Raises:
            ValueError: If zero or more than one source is given, if the
                file/env var is missing, or if the resolved key material is
                shorter than 32 bytes.
        """
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

        if len(resolved) < _MIN_KEK_LENGTH:
            raise ValueError(
                f"KEK material too short: {len(resolved)} bytes, need >= {_MIN_KEK_LENGTH}"
            )

        # Use exactly 32 bytes (AES-256) regardless of a longer supplied secret.
        self._kek = resolved[:32]

    def wrap(self, dek: bytes) -> bytes:
        """Wrap `dek` as `nonce(12B) || AESGCM(dek)`."""
        nonce = os.urandom(_LOCAL_NONCE_LEN)
        ct = AESGCM(self._kek).encrypt(nonce, dek, None)
        return nonce + ct

    def unwrap(self, wrapped_dek: bytes) -> bytes:
        """Reverse `wrap`.

        Raises:
            ValueError: If `wrapped_dek` is too short to contain a nonce and tag.
        """
        if len(wrapped_dek) < _LOCAL_NONCE_LEN + 16:
            raise ValueError("wrapped_dek too short")
        nonce, ct = wrapped_dek[:_LOCAL_NONCE_LEN], wrapped_dek[_LOCAL_NONCE_LEN:]
        result: bytes = AESGCM(self._kek).decrypt(nonce, ct, None)
        return result


class AwsKmsKek:
    """AWS KMS-backed KEK — fully implemented (platform baseline or customer BYOK ARN).

    Requires the `aws` extra (`penguin-crypto[aws]`, i.e. `boto3`). The KMS
    client is never constructed eagerly at import time — only when this
    class is instantiated — so importing `penguin_crypto.envelope` never
    requires `boto3` to be installed.
    """

    def __init__(
        self,
        key_id: str,
        *,
        client: _KmsClient | None = None,
        region_name: str | None = None,
    ) -> None:
        """Bind this provider to one KMS key (platform key id or customer ARN).

        Args:
            key_id: KMS key id or ARN — the design's `kek_ref` column value.
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
            return

        try:
            import boto3  # noqa: PLC0415 - intentionally lazy, see class docstring
        except ImportError as exc:  # pragma: no cover - exercised via missing-extra doc test
            raise ImportError(
                "AwsKmsKek requires the 'aws' extra: pip install 'penguin-crypto[aws]'"
            ) from exc

        self._client = boto3.client("kms", region_name=region_name)

    def wrap(self, dek: bytes) -> bytes:
        """Wrap `dek` via `kms:Encrypt` under `self.key_id`; returns the KMS CiphertextBlob."""
        response = self._client.encrypt(KeyId=self.key_id, Plaintext=dek)
        blob = response["CiphertextBlob"]
        if not isinstance(blob, bytes):
            raise TypeError(f"KMS encrypt returned a non-bytes CiphertextBlob: {type(blob)!r}")
        return blob

    def unwrap(self, wrapped_dek: bytes) -> bytes:
        """Unwrap `wrapped_dek` via `kms:Decrypt`.

        Also verifies the response's `KeyId` matches `self.key_id`, so a
        row's `wrapped_dek` can never be silently unwrapped under a
        different (e.g. another tenant's) KMS key than the one on record.

        Raises:
            ValueError: If the KMS response's KeyId doesn't match `self.key_id`.
        """
        response = self._client.decrypt(CiphertextBlob=wrapped_dek, KeyId=self.key_id)
        response_key_id = response.get("KeyId", "")
        if not isinstance(response_key_id, str) or not response_key_id.endswith(
            self.key_id.split("/")[-1]
        ):
            raise ValueError(
                f"KMS decrypt returned a different key ({response_key_id!r}) than "
                f"expected ({self.key_id})"
            )
        plaintext = response["Plaintext"]
        if not isinstance(plaintext, bytes):
            raise TypeError(f"KMS decrypt returned a non-bytes Plaintext: {type(plaintext)!r}")
        return plaintext


class GcpKmsKek:
    """GCP Cloud KMS-backed KEK — not yet implemented.

    Follow-up: wrap/unwrap via `google-cloud-kms`'s `encrypt`/`decrypt` RPCs
    against a `projects/*/locations/*/keyRings/*/cryptoKeys/*` resource name.
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
    operations (`azure-keyvault-keys` SDK) against a vault key version.
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
    (`hvac` client), returning Vault's `vault:v1:...` ciphertext envelope
    directly as the wrapped-DEK bytes.
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
