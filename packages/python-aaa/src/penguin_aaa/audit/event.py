"""Audit event model and supporting enumerations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Taxonomy of auditable events across authentication, authorization, and sessions."""

    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    TOKEN_ISSUED = "token.issued"
    TOKEN_REVOKED = "token.revoked"
    TOKEN_REFRESHED = "token.refreshed"
    AUTHZ_GRANTED = "authz.granted"
    AUTHZ_DENIED = "authz.denied"
    SPIFFE_AUTH = "spiffe.auth"
    SESSION_CREATED = "session.created"
    SESSION_DESTROYED = "session.destroyed"


class Outcome(StrEnum):
    """High-level result of an audited operation."""

    SUCCESS = "success"
    FAILURE = "failure"


def _default_id() -> str:
    return str(uuid.uuid4())


def _default_timestamp() -> datetime:
    return datetime.now(tz=UTC)


class AuditEvent(BaseModel):
    """Immutable record of a security-relevant event.

    All fields are required except ``ip``, ``user_agent``, ``correlation_id``,
    and ``details``, which are optional to accommodate events emitted before
    full request context is available.
    """

    model_config = {"frozen": True, "strict": True}

    id: str = Field(default_factory=_default_id)
    timestamp: datetime = Field(default_factory=_default_timestamp)
    type: EventType
    subject: str
    action: str
    resource: str
    outcome: Outcome
    ip: str | None = None
    user_agent: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a plain dictionary.

        The timestamp is encoded as an ISO-8601 string with UTC timezone.

        Returns:
            A JSON-serializable mapping of all event fields.
        """
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "type": str(self.type),
            "subject": self.subject,
            "action": self.action,
            "resource": self.resource,
            "outcome": str(self.outcome),
            "ip": self.ip,
            "user_agent": self.user_agent,
            "correlation_id": self.correlation_id,
            "details": self.details,
        }
