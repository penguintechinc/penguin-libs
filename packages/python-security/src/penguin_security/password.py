"""Password hashing and verification utilities.

New hashes are always generated with Argon2id (OWASP-recommended, resistant to
GPU/ASIC attacks). Verification still accepts the legacy
``pbkdf2_sha256$iterations$salt$hash`` format produced by earlier versions of
this module, since existing stored hashes cannot be rehashed without the
original plaintext.

Argon2id is implemented directly here (via ``argon2-cffi``, a base
dependency) rather than by importing ``penguin_security.crypto.kdf`` --
``penguin_security.crypto`` additionally pulls in ``cryptography`` behind the
optional ``crypto`` extra for encryption/ECC/envelope use cases that password
hashing doesn't need, and password hashing is base-package functionality that
must keep working without installing that extra.

``verify_password`` treats ``hashed`` as untrusted, attacker-reachable input
(it is checked *before* authentication succeeds) and never raises for
malformed, out-of-bounds, or otherwise corrupted hash data -- it always fails
closed by returning ``False``, optionally logging a ``WARNING`` with no hash
material. This bounds the cost parameters (Argon2id memory/time/parallelism,
PBKDF2 iterations) that can be read out of a stored hash and used to drive
real cryptographic work, which otherwise lets a corrupted or attacker-planted
hash trigger a denial-of-service (e.g. an absurd Argon2id memory_cost).
``needs_rehash`` is only ever called on a hash that has *already* verified
successfully, so it keeps raising on malformed input -- that should never
happen in practice, and a raise is preferable to silently mis-reporting a
rehash decision for an internal invariant violation.

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
import logging
import os

from argon2.low_level import Type, hash_secret_raw

logger = logging.getLogger(__name__)

# Argon2id parameters. Defined explicitly here (rather than relying on
# argon2-cffi's own defaults implicitly) so a future change to those defaults
# cannot silently change the on-disk hash format without a matching bump here.
_ARGON2_MEMORY_COST = 65536
_ARGON2_TIME_COST = 3
_ARGON2_PARALLELISM = 4
_ARGON2_KEY_LENGTH = 32
_ARGON2_SALT_LENGTH = 32

# Bounds applied to Argon2id parameters *parsed out of a stored hash* before
# they are used to drive real Argon2id computation in verify_password. Without
# this, a corrupted or attacker-planted hash could specify e.g. a multi-GiB
# memory_cost and turn every verification attempt into a denial-of-service.
# Generous relative to our own defaults (m=65536, t=3, p=4) so legitimate
# hashes from a future, stronger default configuration still verify.
_ARGON2_MIN_MEMORY_COST = 1
_ARGON2_MAX_MEMORY_COST = 256 * 1024  # 256 MiB, in KiB (memory_cost is KiB)
_ARGON2_MIN_TIME_COST = 1
_ARGON2_MAX_TIME_COST = 10
_ARGON2_MIN_PARALLELISM = 1
_ARGON2_MAX_PARALLELISM = 8

# Same rationale for the legacy PBKDF2 iteration count.
_PBKDF2_MIN_ITERATIONS = 10_000
_PBKDF2_MAX_ITERATIONS = 2_000_000

# Passwords beyond this length are rejected outright -- bcrypt-style silent
# truncation bugs aside, an unbounded password lets a caller drive unbounded
# CPU/memory cost through hash_password/verify_password.
_MAX_PASSWORD_BYTES = 4096

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_ARGON2_ALGORITHM = "argon2id"


def _derive_argon2id(
    password: str,
    salt: bytes,
    *,
    memory_cost: int,
    time_cost: int,
    parallelism: int,
    key_length: int,
) -> bytes:
    """Derive an Argon2id digest for the given password and salt.

    Raises:
        ValueError: If argon2-cffi rejects the parameters or input (wrapped
            so callers only ever see ValueError, never an argon2-cffi
            internal exception type).
    """
    try:
        return hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=key_length,
            type=Type.ID,
        )
    except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
        raise ValueError("Failed to derive Argon2id hash") from e


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Args:
        password: Password to hash

    Returns:
        str: Hashed password in format: argon2id$m=<memory>,t=<time>,p=<parallelism>$salt$hash

    Raises:
        TypeError: If password is not a string
        ValueError: If password exceeds the maximum length, or Argon2id
            hashing otherwise fails
    """
    if not isinstance(password, str):
        raise TypeError(f"Expected str, got {type(password).__name__}")

    encoded_len = len(password.encode("utf-8"))
    if encoded_len > _MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password exceeds maximum length of {_MAX_PASSWORD_BYTES} bytes (UTF-8 encoded)"
        )

    salt = os.urandom(_ARGON2_SALT_LENGTH)
    derived = _derive_argon2id(
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

    ``hashed`` is treated as untrusted input -- malformed data, an unknown
    algorithm, an oversize password, or cost parameters outside this
    module's accepted bounds all fail closed (return ``False``) rather than
    raising. Only a wrong Python *type* for either argument raises, since
    that is a caller programming error rather than corrupted hash data.

    Args:
        password: Password to verify
        hashed: Hashed password from hash_password()

    Returns:
        bool: True if password matches hash, False otherwise -- including
            for any malformed, out-of-bounds, or unparseable ``hashed`` value

    Raises:
        TypeError: If either argument is not a string
    """
    if not isinstance(password, str):
        raise TypeError(f"Expected str for password, got {type(password).__name__}")
    if not isinstance(hashed, str):
        raise TypeError(f"Expected str for hashed, got {type(hashed).__name__}")

    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        return False

    try:
        algorithm = _parse_algorithm(hashed)
        if algorithm == _ARGON2_ALGORITHM:
            return _verify_argon2id(password, hashed)
        if algorithm == _PBKDF2_ALGORITHM:
            return _verify_pbkdf2_sha256(password, hashed)
        return False
    except Exception:  # noqa: BLE001 -- fail closed on any malformed/unexpected input
        logger.warning("verify_password: failed to verify hash (malformed or unsupported)")
        return False


def needs_rehash(hashed: str) -> bool:
    """Check whether a stored hash should be regenerated with current parameters.

    Legacy PBKDF2-SHA256 hashes always need a rehash. Argon2id hashes need a
    rehash if their encoded cost parameters no longer match this module's
    current defaults (e.g. after a future cost-parameter increase), or if
    their salt/key length differs from the current defaults (e.g. a future
    change to ``_ARGON2_SALT_LENGTH``/``_ARGON2_KEY_LENGTH``).

    Only ever call this on a hash that has *already* verified successfully
    via :func:`verify_password` -- unlike that function, this one raises on
    malformed input rather than failing closed, since a verified hash should
    never be malformed; a raise here signals an internal invariant violation
    rather than attacker-controlled data.

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
        _, params_str, salt_hex, stored_hash_hex = hashed.split("$")
        params = _parse_argon2_params(params_str)
        current = {
            "m": _ARGON2_MEMORY_COST,
            "t": _ARGON2_TIME_COST,
            "p": _ARGON2_PARALLELISM,
        }
        if params != current:
            return True

        try:
            salt_len = len(bytes.fromhex(salt_hex))
            key_len = len(bytes.fromhex(stored_hash_hex))
        except ValueError as e:
            raise ValueError("Invalid hex encoding in hash") from e

        return salt_len != _ARGON2_SALT_LENGTH or key_len != _ARGON2_KEY_LENGTH
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


def _argon2_params_in_bounds(params: dict[str, int]) -> bool:
    """Check that parsed Argon2id cost parameters are within accepted bounds."""
    return (
        _ARGON2_MIN_MEMORY_COST <= params["m"] <= _ARGON2_MAX_MEMORY_COST
        and _ARGON2_MIN_TIME_COST <= params["t"] <= _ARGON2_MAX_TIME_COST
        and _ARGON2_MIN_PARALLELISM <= params["p"] <= _ARGON2_MAX_PARALLELISM
    )


def _verify_argon2id(password: str, hashed: str) -> bool:
    """Verify a password against an argon2id-format hash.

    Raises ValueError for any malformed input; callers (verify_password)
    catch it and fail closed. Cost parameters are bound-checked *before* any
    Argon2id computation is attempted, so a hash with absurd parameters is
    rejected (with a WARNING, no hash material logged) rather than executed.
    """
    _, params_str, salt_hex, stored_hash_hex = hashed.split("$")
    params = _parse_argon2_params(params_str)

    if not _argon2_params_in_bounds(params):
        logger.warning(
            "verify_password: argon2id parameters outside allowed bounds "
            "(memory<=%d KiB, time<=%d, parallelism<=%d); rejecting hash",
            _ARGON2_MAX_MEMORY_COST,
            _ARGON2_MAX_TIME_COST,
            _ARGON2_MAX_PARALLELISM,
        )
        return False

    salt = bytes.fromhex(salt_hex)
    stored_hash = bytes.fromhex(stored_hash_hex)

    derived = _derive_argon2id(
        password,
        salt,
        memory_cost=params["m"],
        time_cost=params["t"],
        parallelism=params["p"],
        key_length=len(stored_hash),
    )

    return hmac.compare_digest(derived, stored_hash)


def _verify_pbkdf2_sha256(password: str, hashed: str) -> bool:
    """Verify a password against a legacy pbkdf2_sha256-format hash.

    Raises ValueError for any malformed input; callers (verify_password)
    catch it and fail closed. The iteration count is bound-checked *before*
    any PBKDF2 computation is attempted, so a hash with an absurd iteration
    count is rejected (with a WARNING, no hash material logged) rather than
    executed.
    """
    _, iterations_str, salt, stored_hash = hashed.split("$")
    iterations = int(iterations_str)

    if not (_PBKDF2_MIN_ITERATIONS <= iterations <= _PBKDF2_MAX_ITERATIONS):
        logger.warning(
            "verify_password: pbkdf2_sha256 iteration count outside allowed bounds "
            "[%d, %d]; rejecting hash",
            _PBKDF2_MIN_ITERATIONS,
            _PBKDF2_MAX_ITERATIONS,
        )
        return False

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
