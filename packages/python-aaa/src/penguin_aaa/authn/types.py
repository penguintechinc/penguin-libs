"""Core types for the penguin-aaa authentication library."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_SUBJECT_LENGTH: int = 256
MAX_TOKEN_SIZE: int = 8192

ALLOWED_RP_ALGORITHMS: frozenset[str] = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)

ALLOWED_PROVIDER_ALGORITHMS: frozenset[str] = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)


class Claims(BaseModel, strict=True):
    """JWT claims payload with mandatory tenant and strict type checking."""

    sub: str = Field(..., max_length=MAX_SUBJECT_LENGTH)
    iss: str
    aud: list[str]
    iat: datetime
    exp: datetime
    scope: list[str]
    roles: list[str] = Field(default_factory=list)
    tenant: str
    teams: list[str] = Field(default_factory=list)
    ext: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sub")
    @classmethod
    def sub_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sub must not be empty or whitespace")
        return value

    @field_validator("iss")
    @classmethod
    def iss_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("iss must not be empty or whitespace")
        return value

    @field_validator("tenant")
    @classmethod
    def tenant_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tenant must not be empty or whitespace")
        return value


class TokenSet(BaseModel, strict=True):
    """OAuth2 / OIDC token response."""

    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"
