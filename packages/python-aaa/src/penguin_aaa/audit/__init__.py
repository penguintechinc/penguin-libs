"""Audit subpackage — structured security event recording and delivery."""

from penguin_aaa.audit.emitter import AuditSink, Emitter
from penguin_aaa.audit.event import AuditEvent, EventType, Outcome

__all__ = [
    "EventType",
    "Outcome",
    "AuditEvent",
    "AuditSink",
    "Emitter",
]
