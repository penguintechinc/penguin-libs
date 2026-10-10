"""Tests for optional ASGI/httpx/sqlalchemy/redis auto-instrumentation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

from penguintechinc_utils.telemetry import instrument as instrument_module
from penguintechinc_utils.telemetry.instrument import instrument


@pytest.fixture(autouse=True)
def _uninstrument_conditional_libs() -> Any:
    """Uninstrument httpx/sqlalchemy/redis after every test.

    Instrumentor state is process-global, so a test that successfully
    instruments httpx would otherwise leak that state into every later
    test in the suite (including other files).
    """
    yield
    for module_name, class_name in instrument_module._CONDITIONAL_INSTRUMENTORS:
        try:
            module = __import__(module_name, fromlist=[class_name])
            instrumentor = getattr(module, class_name)()
            if instrumentor.is_instrumented_by_opentelemetry:
                instrumentor.uninstrument()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass


def _providers() -> tuple[TracerProvider, MeterProvider]:
    """Build a fresh, unconnected tracer/meter provider pair for a test."""
    return TracerProvider(), MeterProvider()


def test_instrument_without_app_is_safe() -> None:
    """app=None must be a no-op that returns None, never raise."""
    tracer_provider, meter_provider = _providers()
    result = instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert result is None


def test_instrument_wraps_asgi_app() -> None:
    """Given an app, instrument() returns a non-None wrapped callable."""
    calls: dict[str, bool] = {}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        calls["hit"] = True

    tracer_provider, meter_provider = _providers()
    wrapped = instrument(app=app, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert wrapped is not None


async def test_wrapped_app_actually_invokes_inner_app() -> None:
    """The wrapped app is a real, callable ASGI app that forwards to the original.

    The plan's own assertion (`is not None`) can't tell a working wrapper from
    a broken stub -- this drives an actual ASGI call through it.
    """
    calls: dict[str, bool] = {}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        calls["hit"] = True

    tracer_provider, meter_provider = _providers()
    wrapped = instrument(app=app, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert wrapped is not None

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "scheme": "http",
        "query_string": b"",
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await wrapped(scope, receive, send)
    assert calls.get("hit") is True


def test_instrument_swallows_unimportable_conditional_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conditional instrumentation module that fails to import is a DEBUG log, not a raise."""

    def _boom(name: str, *args: Any, **kwargs: Any) -> Any:
        raise ImportError(f"no module named {name}")

    monkeypatch.setattr(instrument_module, "import_module", _boom)
    tracer_provider, meter_provider = _providers()
    # Must not raise despite every conditional instrumentor's import failing.
    result = instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert result is None


def test_instrument_swallows_instrumentor_that_raises_on_instrument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An importable instrumentor whose .instrument() raises must still be swallowed."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    def _raise_on_instrument(self: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(HTTPXClientInstrumentor, "instrument", _raise_on_instrument)
    tracer_provider, meter_provider = _providers()
    # Must not raise, and the app-less call must still return None cleanly.
    result = instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert result is None


def test_instrument_logs_debug_on_conditional_import_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing conditional library logs at DEBUG with the module name."""

    def _boom(name: str, *args: Any, **kwargs: Any) -> Any:
        raise ImportError(f"no module named {name}")

    monkeypatch.setattr(instrument_module, "import_module", _boom)
    tracer_provider, meter_provider = _providers()
    with caplog.at_level("DEBUG", logger="penguintechinc_utils.telemetry.instrument"):
        instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)
    assert "httpx" in caplog.text
    assert "sqlalchemy" in caplog.text
    assert "redis" in caplog.text


def test_instrument_can_be_called_twice_without_raising() -> None:
    """Calling instrument() twice (double-instrumentation) must not raise or explode."""
    tracer_provider, meter_provider = _providers()
    instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)
    instrument(app=None, tracer_provider=tracer_provider, meter_provider=meter_provider)


def test_asgi_wrap_failure_falls_back_to_returning_original_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If OpenTelemetryMiddleware construction fails, the original app is still returned.

    Returning None here would silently drop the caller's app and break service
    startup -- worse than the unwrapped-but-working fallback.
    """
    import opentelemetry.instrumentation.asgi as asgi_module

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(asgi_module, "OpenTelemetryMiddleware", _raise)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        pass

    tracer_provider, meter_provider = _providers()
    result: Callable[..., Any] | None = instrument(
        app=app, tracer_provider=tracer_provider, meter_provider=meter_provider
    )
    assert result is app
