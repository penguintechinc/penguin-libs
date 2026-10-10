"""Tests for init(): one call wiring logging plus all three OTel signals."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator

import pytest

import penguintechinc_utils as u
import penguintechinc_utils.telemetry as telemetry_mod
from penguintechinc_utils.telemetry.bridge import SanitizingLogHandler


@pytest.fixture(autouse=True)
def reset_init_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """init() memoises its handle in a module global; each test needs a clean one.

    Without this, the second test in the file would silently receive the first
    test's handle and pass for the wrong reason.
    """
    monkeypatch.setattr(telemetry_mod, "_STATE", None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    yield
    state = telemetry_mod._STATE
    if state is not None:
        state.shutdown()


def _otel_handlers() -> list[logging.Handler]:
    """Every sanitizing OTel handler currently on the root logger."""
    return [h for h in logging.getLogger().handlers if isinstance(h, SanitizingLogHandler)]


def test_init_returns_handle_and_configures_logging() -> None:
    """With no endpoint, init still configures logging and reports not exporting."""
    tel = u.init(service_name="svc")

    assert tel.providers.exporting is False
    assert logging.getLogger().handlers
    tel.shutdown()


def test_init_is_idempotent() -> None:
    """A second init() returns the same handle, warns, and never stacks handlers."""
    first = u.init(service_name="svc")
    before = len(logging.getLogger().handlers)

    with pytest.warns(UserWarning, match="already called"):
        second = u.init(service_name="svc")

    assert first is second
    assert len(logging.getLogger().handlers) == before
    assert len(_otel_handlers()) <= 1


def test_init_attaches_exactly_one_sanitizing_otel_handler() -> None:
    """The OTel log path must exist and must be the sanitizing one."""
    u.init(service_name="svc")
    assert len(_otel_handlers()) == 1


def test_init_sanitizes_a_preexisting_otel_handler_instead_of_adding_one() -> None:
    """Under the opentelemetry-instrument auto-launcher a handler is already present.

    Spec: init() then skips adding its own and wraps the existing one with
    sanitization, so records are neither doubled nor shipped un-redacted.
    """
    from opentelemetry.instrumentation.logging.handler import LoggingHandler

    from penguintechinc_utils.telemetry.config import TelemetryConfig
    from penguintechinc_utils.telemetry.providers import build_providers

    foreign = LoggingHandler(
        logger_provider=build_providers(TelemetryConfig.resolve(service_name="pre")).logger_provider
    )
    logging.getLogger().addHandler(foreign)

    u.init(service_name="svc")

    root = logging.getLogger()
    assert foreign in root.handlers, "the pre-existing handler must be kept"
    assert not _otel_handlers(), "init must not add a second OTel handler"
    assert foreign.filters, "the pre-existing handler must be given a sanitizing filter"

    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "token=sk-live-PREEXISTING", None, None
    )
    for filt in foreign.filters:
        filt.filter(record)
    assert "sk-live-PREEXISTING" not in str(record.msg)
    root.removeHandler(foreign)


def test_otel_handler_excludes_exporter_loggers() -> None:
    """Exporter errors must never re-enter the exporter, or a dead collector loops."""
    u.init(service_name="svc")
    handler = _otel_handlers()[0]

    def record_for(name: str) -> logging.LogRecord:
        return logging.LogRecord(name, logging.ERROR, __file__, 1, "export failed", None, None)

    # Handler.filter returns the (possibly replaced) record on success, not True.
    assert handler.filter(record_for("opentelemetry.exporter.otlp")) is False
    assert handler.filter(record_for("grpc._channel")) is False
    assert handler.filter(record_for("myapp.service"))


def test_init_floors_noisy_loggers_at_warning() -> None:
    """opentelemetry/grpc loggers are floored so their chatter is not exported."""
    u.init(service_name="svc", level=logging.DEBUG)
    assert logging.getLogger("opentelemetry").level == logging.WARNING
    assert logging.getLogger("grpc").level == logging.WARNING


def test_otel_handler_body_is_rendered_json() -> None:
    """The OTLP body must be JSON, not a Python dict repr.

    The OTel handler falls back to record.getMessage() with no formatter, and under
    the stdlib rewire record.msg is a dict -- which would ship "{'event': ...}" with
    single quotes instead of a parseable body.
    """
    u.init(service_name="svc")
    handler = _otel_handlers()[0]
    assert handler.formatter is not None

    # Capture a genuine structlog-originated record: a synthetic LogRecord is a
    # "foreign" record to ProcessorFormatter and would not exercise the same path.
    captured: list[logging.LogRecord] = []

    class _Spy(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    spy = _Spy()
    logging.getLogger().addHandler(spy)
    try:
        u.get_logger("bodytest").info("hello", widget="w1")
    finally:
        logging.getLogger().removeHandler(spy)

    assert captured, "no record reached the root logger"
    payload = json.loads(handler.format(captured[-1]))
    assert payload["event"] == "hello"
    assert payload["widget"] == "w1"
    assert payload["logger"] == "bodytest"


def test_init_returns_wrapped_app() -> None:
    """Passing app= yields an instrumented ASGI app on the handle."""

    async def app(scope: dict[str, object], receive: object, send: object) -> None:
        return None

    tel = u.init(service_name="svc", app=app)
    assert tel.app is not None


def test_init_without_app_leaves_app_none() -> None:
    """No app= means nothing to wrap."""
    assert u.init(service_name="svc").app is None


def test_init_attaches_sinks() -> None:
    """Sinks passed to init() still receive events (0.3.x behaviour, via init)."""
    from penguintechinc_utils.sinks import CallbackSink

    seen: list[dict[str, object]] = []
    u.init(service_name="svc", sinks=[CallbackSink(seen.append)])
    u.get_logger("sinktest").info("via-init")
    assert seen


def test_init_honours_explicit_level_and_format() -> None:
    """Explicit arguments beat env and defaults, and are actually applied."""
    tel = u.init(service_name="svc", level=logging.WARNING, log_format="json")
    assert logging.getLogger().level == logging.WARNING
    assert tel.providers.exporting is False


def test_shutdown_is_idempotent() -> None:
    """shutdown() twice must not raise; atexit may call it after an explicit call."""
    tel = u.init(service_name="svc")
    tel.shutdown()
    tel.shutdown()


def test_sdk_disabled_env_stops_exporting_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_SDK_DISABLED=true keeps logging working and exports nothing."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    tel = u.init(service_name="svc")
    assert tel.providers.exporting is False
    u.get_logger("disabled").info("still works")


def test_later_configure_logging_does_not_drop_the_otel_handler() -> None:
    """Calling the still-public configure_logging() after init() must not break export.

    Adding a sink later is a plausible thing for a consumer to do, and it silently
    removed the OTel log handler init() had installed -- telemetry just stopped, with
    no warning and no failing call.
    """
    u.init(service_name="svc")
    assert len(_otel_handlers()) == 1

    u.configure_logging(level=logging.INFO, json_output=True)

    assert len(_otel_handlers()) == 1, "configure_logging() tore off the OTel handler"


def test_shutdown_swallows_provider_failures() -> None:
    """A provider that raises on flush or shutdown must not break process exit.

    "A dead exporter never breaks the app" has to hold on the exit path too, where a
    raised exception would turn a telemetry problem into a non-zero exit status.
    """
    tel = u.init(service_name="svc")

    class _Hostile:
        def force_flush(self, timeout_millis: int = 0) -> bool:
            raise RuntimeError("flush exploded")

        def shutdown(self) -> None:
            raise RuntimeError("shutdown exploded")

    hostile = _Hostile()
    tel.providers.tracer_provider = hostile  # type: ignore[assignment]
    tel.providers.meter_provider = hostile  # type: ignore[assignment]
    tel.providers.logger_provider = hostile  # type: ignore[assignment]

    tel.shutdown()  # must not raise


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_init_in_forked_worker_is_safe() -> None:
    """Pre-fork servers call init() per worker; the SDK must not deadlock after fork."""
    if not hasattr(os, "fork") or sys.platform == "win32":  # pragma: no cover - platform gate
        pytest.skip("no os.fork")

    pid = os.fork()
    if pid == 0:  # pragma: no cover - runs in the forked child, never measured
        try:
            import penguintechinc_utils as child_u

            child_u.init(service_name="child")
            child_u.get_logger("c").info("in-child")
            os._exit(0)
        except BaseException:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status)
    assert os.WEXITSTATUS(status) == 0


def test_otel_export_does_not_warn_about_structlog_internals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """structlog's private record attributes must not reach OTLP attributes.

    LoggingHandler copies every non-reserved record attribute into the log record's
    attributes, and structlog attaches `_logger` -- a logger object, which OTel
    rejects with a warning on every single log line.
    """
    u.init(service_name="svc")
    u.get_logger("metatest").info("hello", widget="w1")
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "Invalid type" not in text
    assert "_FixedFindCallerLogger" not in text


def test_structlog_meta_attrs_are_restored_after_otel_emit() -> None:
    """Hiding structlog's internals must be temporary, or the console path breaks."""
    u.init(service_name="svc")
    handler = _otel_handlers()[0]
    record = logging.LogRecord("x", logging.INFO, __file__, 1, {"event": "hi"}, None, None)
    record._logger = object()  # type: ignore[attr-defined]
    record._name = "x"  # type: ignore[attr-defined]

    handler.emit(record)

    assert hasattr(record, "_logger")
    assert hasattr(record, "_name")
