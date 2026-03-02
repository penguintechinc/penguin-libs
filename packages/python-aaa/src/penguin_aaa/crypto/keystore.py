"""Key store implementations — in-memory and file-backed."""

import json
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from penguin_aaa.crypto.jwks import public_key_to_jwk

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

PrivateKey = RSAPrivateKey | EllipticCurvePrivateKey
PublicKey = RSAPublicKey | EllipticCurvePublicKey


@runtime_checkable
class KeyStore(Protocol):
    """Protocol for signing key stores used by OIDCProvider."""

    def get_signing_key(self) -> tuple[PrivateKey, str]:
        """
        Return the current active signing key and its key ID.

        Returns:
            A (private_key, kid) tuple.
        """
        ...

    def get_jwks(self) -> dict[str, Any]:
        """
        Return the public JWKS for all managed keys.

        Returns:
            A dict with a "keys" list of JWK dicts.
        """
        ...

    def rotate_key(self) -> None:
        """Generate a new signing key, retiring the oldest one if needed."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _algorithm_for_key(key: PrivateKey) -> str:
    if isinstance(key, RSAPrivateKey):
        return "RS256"
    curve = key.curve
    curve_alg_map = {
        "secp256r1": "ES256",
        "secp384r1": "ES384",
        "secp521r1": "ES512",
    }
    return curve_alg_map.get(curve.name, "ES256")


def _generate_key(algorithm: str) -> PrivateKey:
    if algorithm.startswith("RS") or algorithm.startswith("PS"):
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    if algorithm == "ES256":
        return ec.generate_private_key(ec.SECP256R1())
    if algorithm == "ES384":
        return ec.generate_private_key(ec.SECP384R1())
    if algorithm == "ES512":
        return ec.generate_private_key(ec.SECP521R1())
    raise ValueError(f"Cannot generate key for unsupported algorithm: {algorithm}")


def _private_key_to_pem(key: PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _load_private_key_from_pem(pem: bytes) -> PrivateKey:
    loaded = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(loaded, (RSAPrivateKey, EllipticCurvePrivateKey)):
        raise TypeError(f"Loaded key type {type(loaded).__name__} is not supported")
    return loaded


# ---------------------------------------------------------------------------
# MemoryKeyStore
# ---------------------------------------------------------------------------


class MemoryKeyStore:
    """
    In-memory key store for development and testing.

    Generates a signing key on construction and supports key rotation.
    Keys are never persisted.
    """

    _MAX_KEYS: int = 3

    def __init__(self, algorithm: str = "RS256") -> None:
        self._algorithm = algorithm
        self._keys: list[tuple[PrivateKey, str]] = []
        self.rotate_key()

    def get_signing_key(self) -> tuple[PrivateKey, str]:
        """Return the most recently generated signing key and its kid."""
        return self._keys[-1]

    def get_jwks(self) -> dict[str, Any]:
        """Return a JWKS dict containing all active public keys."""
        jwk_list: list[dict[str, Any]] = []
        for private_key, kid in self._keys:
            public_key: PublicKey = private_key.public_key()  # type: ignore[assignment]
            jwk_list.append(public_key_to_jwk(public_key, kid, self._algorithm))
        return {"keys": jwk_list}

    def rotate_key(self) -> None:
        """Generate a new signing key.  Retains at most _MAX_KEYS keys."""
        new_key = _generate_key(self._algorithm)
        new_kid = str(uuid.uuid4())
        self._keys.append((new_key, new_kid))
        if len(self._keys) > self._MAX_KEYS:
            self._keys.pop(0)


# ---------------------------------------------------------------------------
# FileKeyStore
# ---------------------------------------------------------------------------

_FileStoreData = dict[str, list[dict[str, str]]]


class FileKeyStore:
    """
    File-backed key store that persists PEM keys to a JSON file.

    The JSON file contains a list of {"kid": "...", "pem": "..."} entries.
    Keys are loaded on construction; rotation appends a new key and saves.
    """

    _MAX_KEYS: int = 3

    def __init__(self, path: Path, algorithm: str = "RS256") -> None:
        self._path = path
        self._algorithm = algorithm
        self._keys: list[tuple[PrivateKey, str]] = []
        self._load_or_init()

    # ------------------------------------------------------------------
    # KeyStore protocol implementation
    # ------------------------------------------------------------------

    def get_signing_key(self) -> tuple[PrivateKey, str]:
        """Return the most recently persisted signing key and its kid."""
        return self._keys[-1]

    def get_jwks(self) -> dict[str, Any]:
        """Return a JWKS dict containing all active public keys."""
        jwk_list: list[dict[str, Any]] = []
        for private_key, kid in self._keys:
            public_key: PublicKey = private_key.public_key()  # type: ignore[assignment]
            jwk_list.append(public_key_to_jwk(public_key, kid, self._algorithm))
        return {"keys": jwk_list}

    def rotate_key(self) -> None:
        """Generate a new signing key, persist all active keys, retire oldest."""
        new_key = _generate_key(self._algorithm)
        new_kid = str(uuid.uuid4())
        self._keys.append((new_key, new_kid))
        if len(self._keys) > self._MAX_KEYS:
            self._keys.pop(0)
        self._save()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_or_init(self) -> None:
        if self._path.exists():
            self._load()
        else:
            self.rotate_key()

    def _load(self) -> None:
        text = self._path.read_text(encoding="utf-8")
        data: _FileStoreData = json.loads(text)
        entries = data.get("keys", [])
        self._keys = []
        for entry in entries:
            pem = entry["pem"].encode("utf-8")
            kid = entry["kid"]
            self._keys.append((_load_private_key_from_pem(pem), kid))

    def _save(self) -> None:
        entries = [
            {"kid": kid, "pem": _private_key_to_pem(key).decode("utf-8")} for key, kid in self._keys
        ]
        data: _FileStoreData = {"keys": entries}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
