"""Static-key JWT verification — pre-distributed PEM public keys (no JWKS).

For deployments where the signer's public key is distributed out of band
(e.g. a Kubernetes Secret mounted into every verifier pod) instead of being
fetched from an OIDC discovery/JWKS endpoint. Verifier services hold only the
public key and can never mint tokens.

Security contract (fail closed on every path):

- asymmetric algorithms only (default ``ES256``/``RS256``); ``HS256``/``none``
  are rejected, blocking the public-key-as-HMAC algorithm-confusion attack
- ``iss`` and ``aud`` validated; ``exp``/``iat``/``tenant`` required
- claims are validated through :class:`~penguin_aaa.authn.types.Claims`,
  which mandates a non-empty ``tenant``
- no public key configured → every verification fails

The public key may be pinned in config or loaded at call time from an
environment variable / file path (``load_key_from_env_or_file``), which
supports key rotation without a process restart.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt

from penguin_aaa.authn.oidc_rp import _normalise_list_fields
from penguin_aaa.authn.types import ALLOWED_RP_ALGORITHMS, MAX_TOKEN_SIZE, Claims

logger = logging.getLogger(__name__)


def load_key_from_env_or_file(env_var: str, file_env_var: str) -> str | None:
    """Load a PEM key from an env var, or from the file a second env var names.

    Args:
        env_var: Environment variable holding the PEM content directly.
        file_env_var: Environment variable holding a path to a PEM file.

    Returns:
        The PEM string, or None if neither source is available.
    """
    value = os.getenv(env_var)
    if value:
        return value

    path = os.getenv(file_env_var)
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()

    return None


@dataclass(slots=True)
class StaticKeyConfig:
    """Configuration for a static-key JWT verifier.

    Provide ``public_key`` to pin the key for the verifier's lifetime, or
    leave it None to load from ``public_key_env`` / ``public_key_file_env``
    on every verification (supports rotation without restart).
    """

    issuer: str
    audience: str
    public_key: str | None = None
    public_key_env: str = "JWT_PUBLIC_KEY"
    public_key_file_env: str = "JWT_PUBLIC_KEY_FILE"
    algorithms: list[str] = field(default_factory=lambda: ["ES256", "RS256"])
    required_claims: tuple[str, ...] = ("exp", "iat", "tenant")
    clock_skew: timedelta = field(default_factory=lambda: timedelta(seconds=30))

    def __post_init__(self) -> None:
        if not self.issuer.strip():
            raise ValueError("issuer must not be empty")
        if not self.audience.strip():
            raise ValueError("audience must not be empty")
        for alg in self.algorithms:
            if alg not in ALLOWED_RP_ALGORITHMS:
                raise ValueError(
                    f"Algorithm '{alg}' is not allowed. Permitted: {sorted(ALLOWED_RP_ALGORITHMS)}"
                )


class StaticKeyVerifier:
    """Verify JWTs against a pre-distributed PEM public key."""

    def __init__(self, config: StaticKeyConfig) -> None:
        self._config = config

    def _resolve_key(self) -> str | None:
        if self._config.public_key:
            return self._config.public_key
        return load_key_from_env_or_file(
            self._config.public_key_env, self._config.public_key_file_env
        )

    def validate_token(self, raw_token: str) -> Claims:
        """Validate a raw JWT string and return its parsed claims.

        Args:
            raw_token: The encoded JWT string.

        Returns:
            Validated Claims instance (tenant guaranteed non-empty).

        Raises:
            ValueError: If no public key is configured, the token is oversized,
                or required claims are missing/malformed.
            jwt.PyJWTError: On signature, algorithm, expiry, issuer, or
                audience failures.
        """
        if len(raw_token) > MAX_TOKEN_SIZE:
            raise ValueError(f"Token exceeds maximum allowed size of {MAX_TOKEN_SIZE} bytes")

        public_key = self._resolve_key()
        if not public_key:
            raise ValueError(
                "No JWT public key configured "
                f"(set {self._config.public_key_env} or {self._config.public_key_file_env})"
            )

        skew_seconds = int(self._config.clock_skew.total_seconds())
        payload = jwt.decode(
            raw_token,
            public_key,
            algorithms=self._config.algorithms,
            audience=self._config.audience,
            issuer=self._config.issuer,
            leeway=skew_seconds,
            options={"require": list(self._config.required_claims)},
        )

        # jwt.decode returns dict[str, Any]; normalise before pydantic validation
        _normalise_list_fields(payload, ("aud", "scope", "roles", "teams"))

        # JWT iat/exp are Unix timestamps (int) — convert for pydantic strict mode
        for field_name in ("iat", "exp"):
            val = payload.get(field_name)
            if isinstance(val, (int, float)):
                payload[field_name] = datetime.fromtimestamp(val, tz=UTC)

        return Claims.model_validate(payload)

    def verify_token(self, raw_token: str) -> Claims:
        """Alias for validate_token — parity with OIDCRelyingParty."""
        return self.validate_token(raw_token)

    def verify_or_none(self, raw_token: str) -> Claims | None:
        """Fail-closed convenience: return Claims, or None on ANY failure.

        For callers that gate access with a boolean decision rather than
        propagating auth errors (e.g. DNS zone checks).
        """
        try:
            return self.validate_token(raw_token)
        except (jwt.InvalidTokenError, jwt.DecodeError, jwt.InvalidAlgorithmError) as exc:
            # Crypto/signature verification failures
            logger.warning(
                "Static-key JWT validation failed (%s)", type(exc).__name__, exc_info=True
            )
            return None
        except Exception as exc:
            # Network, transient, or other unexpected errors
            logger.warning(
                "Static-key JWT verification error (%s)", type(exc).__name__, exc_info=True
            )
            return None
