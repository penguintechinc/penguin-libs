"""Password hashing and verification utilities.

New hashes are always generated with Argon2id (OWASP-recommended, resistant to
GPU/ASIC attacks) via :mod:`penguin_security.crypto.kdf`. Verification still
accepts the legacy ``pbkdf2_sha256$iterations$salt$hash`` format produced by
earlier versions of this module, since existing stored hashes cannot be
rehashed without the original plaintext.

Migration path for callers with existing PBKDF2 hashes in storage:
    1. On successful login, call ``needs_rehash(stored_hash)``.
    2. If it returns ``True``, call ``hash_password(password)`` with the
       plaintext just verified and persist the new Argon2id hash in place of
       the old one.
    3. No bulk migration or forced password reset is required -- hashes are
       upgraded lazily, one user at a time, as they log in.
"""

import hashlib
import hmac

from .crypto.kdf import derive_key_argon2id, generate_salt

# Argon2id parameters -- match penguin_security.crypto.kdf.derive_key_argon2id's
# own defaults. Defined explicitly here (rather than relying on the KDF's
# defaults implicitly) so a future change to the KDF's defaults cannot
# silently change the on-disk hash format without a matching bump here.
_ARGON2_MEMORY_COST = 65536
_ARGON2_TIME_COST = 3
_ARGON2_PARALLELISM = 4
_ARGON2_KEY_LENGTH = 32

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_ARGON2_ALGORITHM = "argon2id"


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Args:
        password: Password to hash

    Returns:
        str: Hashed password in format: argon2id$m=<memory>,t=<time>,p=<parallelism>$salt$hash

    Raises:
        TypeError: If password is not a string
    """
    if not isinstance(password, str):
        raise TypeError(f"Expected str, got {type(password).__name__}")

    salt = generate_salt()
    derived = derive_key_argon2id(
        password,
        salt,
        memory_cost=_ARGON2_MEMORY_COST,
        time_cost=_ARGON2_TIME_COST,
        parallelism=_ARGON2_PARALLELISM,
        key_length=_ARGON2_KEY_LENGTH,
    )

    params = f"m={_ARGON2_MEMORY_COST},t={_ARGON2_TIME_COST},p={_ARGON2_PARALLELISM}"
    return f"{_ARGON2_ALGORITHM}${params}${salt.hex()}${derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash.

    Supports both the current Argon2id format and the legacy PBKDF2-SHA256
    format for backward compatibility with hashes created before this module
    switched to Argon2id. Use :func:`needs_rehash` to detect legacy hashes
    that should be upgraded on next successful login.

    Args:
        password: Password to verify
        hashed: Hashed password from hash_password()

    Returns:
        bool: True if password matches hash, False otherwise

    Raises:
        TypeError: If either argument is not a string
        ValueError: If hash format is invalid
    """
    if not isinstance(password, str):
        raise TypeError(f"Expected str for password, got {type(password).__name__}")
    if not isinstance(hashed, str):
        raise TypeError(f"Expected str for hashed, got {type(hashed).__name__}")

    algorithm = _parse_algorithm(hashed)

    if algorithm == _ARGON2_ALGORITHM:
        return _verify_argon2id(password, hashed)
    if algorithm == _PBKDF2_ALGORITHM:
        return _verify_pbkdf2_sha256(password, hashed)
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def needs_rehash(hashed: str) -> bool:
    """Check whether a stored hash should be regenerated with current parameters.

    Legacy PBKDF2-SHA256 hashes always need a rehash. Argon2id hashes need a
    rehash only if their encoded parameters no longer match this module's
    current defaults (e.g. after a future cost-parameter increase).

    Args:
        hashed: Hashed password from hash_password()

    Returns:
        bool: True if the hash should be regenerated on next successful login

    Raises:
        TypeError: If hashed is not a string
        ValueError: If hash format is invalid
    """
    if not isinstance(hashed, str):
        raise TypeError(f"Expected str for hashed, got {type(hashed).__name__}")

    algorithm = _parse_algorithm(hashed)

    if algorithm == _PBKDF2_ALGORITHM:
        return True
    if algorithm == _ARGON2_ALGORITHM:
        _, params_str, _, _ = hashed.split("$")
        params = _parse_argon2_params(params_str)
        current = {
            "m": _ARGON2_MEMORY_COST,
            "t": _ARGON2_TIME_COST,
            "p": _ARGON2_PARALLELISM,
        }
        return params != current
    raise ValueError(f"Unsupported algorithm: {algorithm}")


def _parse_algorithm(hashed: str) -> str:
    """Extract and validate the algorithm identifier from an encoded hash."""
    parts = hashed.split("$")
    if len(parts) != 4:
        raise ValueError("Invalid hash format")
    return parts[0]


def _parse_argon2_params(params_str: str) -> dict[str, int]:
    """Parse an argon2id params segment (``m=65536,t=3,p=4``) into a dict."""
    params: dict[str, int] = {}
    try:
        for item in params_str.split(","):
            key, value = item.split("=")
            params[key] = int(value)
    except ValueError as e:
        raise ValueError("Invalid argon2id parameters in hash") from e
    if not {"m", "t", "p"} <= params.keys():
        raise ValueError("Invalid argon2id parameters in hash")
    return params


def _verify_argon2id(password: str, hashed: str) -> bool:
    """Verify a password against an argon2id-format hash."""
    _, params_str, salt_hex, stored_hash_hex = hashed.split("$")
    params = _parse_argon2_params(params_str)

    try:
        salt = bytes.fromhex(salt_hex)
        stored_hash = bytes.fromhex(stored_hash_hex)
    except ValueError as e:
        raise ValueError("Invalid hex encoding in hash") from e

    derived = derive_key_argon2id(
        password,
        salt,
        memory_cost=params["m"],
        time_cost=params["t"],
        parallelism=params["p"],
        key_length=len(stored_hash),
    )

    return hmac.compare_digest(derived, stored_hash)


def _verify_pbkdf2_sha256(password: str, hashed: str) -> bool:
    """Verify a password against a legacy pbkdf2_sha256-format hash."""
    _, iterations_str, salt, stored_hash = hashed.split("$")

    try:
        iterations = int(iterations_str)
    except ValueError as e:
        raise ValueError("Invalid iterations in hash") from e

    # Hash the provided password with the same salt and iterations
    hash_obj = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    computed_hash = hash_obj.hex()

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_hash, stored_hash)
