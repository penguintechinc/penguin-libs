"""Password hashing and verification utilities."""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """
    Hash a password using PBKDF2 with SHA256.

    Args:
        password: Password to hash

    Returns:
        str: Hashed password in format: algorithm$iterations$salt$hash

    Raises:
        TypeError: If password is not a string
    """
    if not isinstance(password, str):
        raise TypeError(f"Expected str, got {type(password).__name__}")

    # Use PBKDF2 with SHA256
    iterations = 100000
    salt = secrets.token_hex(16)  # 32-character salt

    # Hash using PBKDF2
    hash_obj = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    hash_hex = hash_obj.hex()

    # Return in standard format: algorithm$iterations$salt$hash
    return f"pbkdf2_sha256${iterations}${salt}${hash_hex}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.

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

    # Parse the hash
    parts = hashed.split("$")
    if len(parts) != 4:
        raise ValueError("Invalid hash format")

    algorithm, iterations_str, salt, stored_hash = parts

    if algorithm != "pbkdf2_sha256":
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    try:
        iterations = int(iterations_str)
    except ValueError:
        raise ValueError("Invalid iterations in hash")

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
