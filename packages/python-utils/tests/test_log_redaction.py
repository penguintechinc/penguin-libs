"""
Regression tests for mid-string PII redaction in SanitizedLogger.

Covers gh finding: EMAIL_REGEX was anchored via re.match(), so an email
embedded anywhere other than position 0 of a string (a log message, or a
dict value that is not itself a bare email) passed through unredacted.
"""

import logging
from typing import Any

from penguintechinc_utils import CallbackSink, SanitizedLogger, configure_logging
from penguintechinc_utils.logging import _sanitize_string, sanitize_log_data


class TestMidStringEmailRedaction:
    def test_email_embedded_in_message_is_redacted(self) -> None:
        received: list[dict[str, Any]] = []
        sink = CallbackSink(received.append)
        configure_logging(level=logging.DEBUG, json_output=False, sinks=[sink])

        log = SanitizedLogger("TestMidStringRedaction")
        log.info("user alice@example.com logged in")

        assert len(received) >= 1
        event = received[-1]
        rendered = str(event)
        assert "alice@example.com" not in rendered
        assert event.get("event") == "user [email]@example.com logged in"

    def test_email_embedded_in_dict_value_is_redacted(self) -> None:
        data = {"note": "contact bob@example.com"}
        result = sanitize_log_data(data)
        assert result["note"] == "contact [email]@example.com"
        assert "bob@example.com" not in result["note"]

    def test_key_based_redaction_still_works(self) -> None:
        data = {"password": "x"}
        result = sanitize_log_data(data)
        assert result["password"] == "[REDACTED]"

    def test_plain_message_without_pii_is_unchanged(self) -> None:
        assert _sanitize_string("no sensitive data here") == "no sensitive data here"

    def test_multiple_embedded_emails_all_redacted(self) -> None:
        value = "cc: alice@example.com, bob@example.org"
        result = _sanitize_string(value)
        assert "alice@example.com" not in result
        assert "bob@example.org" not in result
        assert result == "cc: [email]@example.com, [email]@example.org"

    def test_full_email_value_still_matches_prior_behavior(self) -> None:
        # Backward compatibility: a value that IS just an email address
        # still redacts to the same "[email]@domain" form as before.
        data = {"contact": "alice@example.com"}
        result = sanitize_log_data(data)
        assert result["contact"] == "[email]@example.com"
