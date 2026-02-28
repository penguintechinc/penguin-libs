"""JWKS serialisation — convert public keys to RFC 7517 JWK format."""

import base64
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePublicKey,
    SECP256R1,
    SECP384R1,
    SECP521R1,
)
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey


def public_key_to_jwk(
    key: RSAPublicKey | EllipticCurvePublicKey,
    kid: str,
    alg: str,
) -> dict[str, Any]:
    """
    Serialise a public key to a JSON Web Key (JWK) dict.

    Supports RSA and EC (P-256, P-384, P-521) key types.  All binary fields
    use base64url encoding without padding as required by RFC 7517.

    Args:
        key: The public key to serialise.
        kid: Key ID to embed in the JWK.
        alg: Algorithm identifier (e.g. "RS256", "ES256").

    Returns:
        A dict representing the JWK.

    Raises:
        TypeError: If the key type is not RSA or EC.
        ValueError: If the EC curve is not P-256, P-384, or P-521.
    """
    if isinstance(key, RSAPublicKey):
        return _rsa_to_jwk(key, kid, alg)
    if isinstance(key, EllipticCurvePublicKey):
        return _ec_to_jwk(key, kid, alg)
    raise TypeError(f"Unsupported key type: {type(key).__name__}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    """Base64url-encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_to_bytes(value: int, length: int) -> bytes:
    """Encode an integer as big-endian bytes of exactly `length` bytes."""
    return value.to_bytes(length, byteorder="big")


def _rsa_to_jwk(key: RSAPublicKey, kid: str, alg: str) -> dict[str, Any]:
    pub = key.public_numbers()
    key_size_bytes = (key.key_size + 7) // 8
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": alg,
        "kid": kid,
        "n": _b64url(_int_to_bytes(pub.n, key_size_bytes)),
        "e": _b64url(_int_to_bytes(pub.e, (pub.e.bit_length() + 7) // 8)),
    }


_EC_CURVE_NAMES: dict[type, tuple[str, int]] = {
    SECP256R1: ("P-256", 32),
    SECP384R1: ("P-384", 48),
    SECP521R1: ("P-521", 66),
}


def _ec_to_jwk(key: EllipticCurvePublicKey, kid: str, alg: str) -> dict[str, Any]:
    curve_type = type(key.curve)
    if curve_type not in _EC_CURVE_NAMES:
        raise ValueError(
            f"Unsupported EC curve: {key.curve.name}. "
            f"Supported: {[v[0] for v in _EC_CURVE_NAMES.values()]}"
        )

    crv_name, coord_bytes = _EC_CURVE_NAMES[curve_type]
    pub = key.public_numbers()

    return {
        "kty": "EC",
        "use": "sig",
        "alg": alg,
        "kid": kid,
        "crv": crv_name,
        "x": _b64url(_int_to_bytes(pub.x, coord_bytes)),
        "y": _b64url(_int_to_bytes(pub.y, coord_bytes)),
    }
