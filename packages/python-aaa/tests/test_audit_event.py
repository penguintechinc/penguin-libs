"""Tests for penguin_aaa.audit.event — AuditEvent, EventType, Outcome."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from penguin_aaa.audit.event import AuditEvent, EventType, Outcome


class TestEventType:
    def test_all_expected_values_present(self):
        expected = {
            "auth.success",
            "auth.failure",
            "token.issued",
            "token.revoked",
            "token.refreshed",
            "authz.granted",
            "authz.denied",
            "spiffe.auth",
            "session.created",
            "session.destroyed",
        }
        actual = {e.value for e in EventType}
        assert expected == actual

    def test_str_enum_value_is_string(self):
        assert str(EventType.AUTH_SUCCESS) == "auth.success"
        assert EventType.AUTH_SUCCESS == "auth.success"


class TestOutcome:
    def test_success_and_failure_present(self):
        assert Outcome.SUCCESS == "success"
        assert Outcome.FAILURE == "failure"


class TestAuditEvent:
    def _minimal(self, **overrides) -> dict:
        base = {
            "type": EventType.AUTH_SUCCESS,
            "subject": "user-123",
            "action": "GET",
            "resource": "/api/reports",
            "outcome": Outcome.SUCCESS,
        }
        base.update(overrides)
        return base

    def test_valid_event_created(self):
        event = AuditEvent(**self._minimal())
        assert event.subject == "user-123"
        assert event.outcome == Outcome.SUCCESS

    def test_id_generated_as_uuid(self):
        import uuid
        event = AuditEvent(**self._minimal())
        uuid.UUID(event.id)  # raises if not valid UUID

    def test_timestamp_defaults_to_utc_now(self):
        event = AuditEvent(**self._minimal())
        assert event.timestamp.tzinfo is not None
        assert event.timestamp.tzinfo == timezone.utc

    def test_optional_fields_default_to_none(self):
        event = AuditEvent(**self._minimal())
        assert event.ip is None
        assert event.user_agent is None
        assert event.correlation_id is None

    def test_details_defaults_to_empty_dict(self):
        event = AuditEvent(**self._minimal())
        assert event.details == {}

    def test_optional_fields_accepted(self):
        event = AuditEvent(
            **self._minimal(
                ip="192.168.1.1",
                user_agent="Mozilla/5.0",
                correlation_id="corr-123",
                details={"status_code": 200},
            )
        )
        assert event.ip == "192.168.1.1"
        assert event.user_agent == "Mozilla/5.0"
        assert event.correlation_id == "corr-123"
        assert event.details["status_code"] == 200

    def test_event_is_immutable(self):
        from pydantic import ValidationError
        event = AuditEvent(**self._minimal())
        with pytest.raises((ValidationError, TypeError)):
            event.subject = "changed"  # type: ignore[misc]

    def test_to_dict_returns_serializable_mapping(self):
        event = AuditEvent(**self._minimal(correlation_id="c-1"))
        d = event.to_dict()
        assert d["subject"] == "user-123"
        assert d["type"] == "auth.success"
        assert d["outcome"] == "success"
        assert isinstance(d["timestamp"], str)
        assert "T" in d["timestamp"]
        assert d["correlation_id"] == "c-1"

    def test_to_dict_includes_all_keys(self):
        event = AuditEvent(**self._minimal())
        keys = set(event.to_dict().keys())
        expected = {
            "id", "timestamp", "type", "subject", "action",
            "resource", "outcome", "ip", "user_agent", "correlation_id", "details",
        }
        assert keys == expected

    def test_strict_mode_rejects_wrong_type(self):
        with pytest.raises(ValidationError):
            AuditEvent(**self._minimal(subject=123))  # type: ignore[arg-type]

    def test_missing_required_field_raises(self):
        data = self._minimal()
        del data["subject"]
        with pytest.raises(ValidationError):
            AuditEvent(**data)
