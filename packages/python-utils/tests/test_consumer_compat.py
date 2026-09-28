"""The real 0.3.x call sites from the consuming services must keep working.

Mirrors how gough, license-server, penguincloud and elder actually use this package,
so an API-shape regression fails here rather than in someone else's deploy.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from penguintechinc_utils import SanitizedLogger, get_logger, sanitize_log_data
from penguintechinc_utils.logging import configure_logging_from_env


def test_gough_and_license_server_get_logger_call_site() -> None:
    """gough / license-server: `get_logger(__name__)` and log with kwargs."""
    log = get_logger("gough.service")
    assert log is not None
    log.info("service started", version="1.2.3")


def test_get_logger_with_explicit_level_call_site() -> None:
    """The 0.3.x two-argument form still works, positionally and by keyword."""
    assert get_logger("svc", logging.DEBUG) is not None
    assert get_logger("svc", level=logging.DEBUG) is not None


def test_penguincloud_sanitized_logger_call_site() -> None:
    """penguincloud: `SanitizedLogger(name)` then `.info(msg, data_dict)`."""
    log = SanitizedLogger("penguincloud.api")
    log.info("request", {"password": "p", "user_uuid": "abc-123"})
    log.debug("d", {"x": 1})
    log.warning("w")
    log.error("e", {"token": "t"})
    log.critical("c")


def test_elder_sanitize_log_data_call_site() -> None:
    """elder: calls `sanitize_log_data(dict)` directly and inspects the result."""
    out = sanitize_log_data({"secret": "s", "email": "a@b.com", "keep": "me"})
    assert out["secret"] == "[REDACTED]"
    assert out["email"] == "[email]"
    assert out["keep"] == "me"


def test_configure_logging_from_env_call_site(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns a list even with nothing configured, so callers can splat it."""
    for var in (
        "LOG_CLOUDWATCH_GROUP",
        "LOG_CLOUDWATCH_STREAM",
        "LOG_GCP_PROJECT",
        "LOG_GCP_LOG_NAME",
        "LOG_KAFKA_SERVERS",
        "LOG_KAFKA_TOPIC",
    ):
        monkeypatch.delenv(var, raising=False)
    sinks = configure_logging_from_env()
    assert isinstance(sinks, list)
    assert sinks == []


def test_sanitize_log_data_tolerates_non_dict_input() -> None:
    """0.3.x returned non-dict input unchanged; callers rely on that leniency."""
    assert sanitize_log_data("not a dict") == "not a dict"  # type: ignore[arg-type]
    assert sanitize_log_data(None) is None  # type: ignore[arg-type]


def test_logs_only_setup_needs_no_telemetry() -> None:
    """A consumer that never calls init() must still get working logging.

    configure_logging stays logs-only; requiring init() would have been a breaking
    change for every 0.3.x consumer.
    """
    from penguintechinc_utils import configure_logging

    configure_logging(level=logging.INFO, json_output=True)
    get_logger("logs.only").info("works without init")


def test_sink_protocol_is_still_structural() -> None:
    """A consumer's own duck-typed sink class must still satisfy Sink."""
    from penguintechinc_utils import Sink

    class MySink:
        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    assert isinstance(MySink(), Sink)
