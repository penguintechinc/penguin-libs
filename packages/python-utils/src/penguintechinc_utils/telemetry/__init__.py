"""One-call logging + OpenTelemetry setup for penguin-utils.

`init()` is the whole public surface: it resolves configuration from arguments, then
env, then defaults; builds the three OTel providers; routes structlog through stdlib
logging; attaches a sanitizing OTel log handler; and optionally instruments an ASGI
app. Telemetry failure is never an application failure, so every step that can fail
because the outside world is unavailable degrades to a warning instead.
"""

from __future__ import annotations

import atexit
import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.logging.handler import LoggingHandler

from ..logging import _shared_processors, configure_logging
from .bridge import SanitizingFilter, SanitizingLogHandler, SanitizingSpanProcessorFactory
from .config import TelemetryConfig
from .instrument import instrument as _instrument_app
from .providers import Providers, build_providers

_LOG = logging.getLogger(__name__)

# The handle from the first init(); a second call returns it rather than stacking
# handlers and providers on top of the first.
_STATE: Telemetry | None = None

# Total milliseconds shutdown() may spend flushing, split across the three signals.
# The spec requires a hard budget: process exit must never hang on a dead collector.
_SHUTDOWN_BUDGET_MS = 5000

# Loggers whose records must never be exported. An exporter that logs its own
# failures through a handler that exports would feed itself forever.
_NOISY_LOGGER_PREFIXES = ("opentelemetry", "grpc")


class _ExcludeLoggers(logging.Filter):
    """Drop records from logger names that must not reach the OTel exporter."""

    def __init__(self, prefixes: tuple[str, ...]) -> None:
        """Store the logger-name prefixes to exclude."""
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        """Admit the record unless its logger is one of the excluded ones."""
        return not record.name.startswith(self._prefixes)


@dataclass(slots=True)
class Telemetry:
    """Handle returned by `init()`: the providers, the wrapped app, and shutdown.

    Held so a service can flush deliberately before exit and so tests can assert on
    what was configured; `shutdown()` is also registered with `atexit`.
    """

    providers: Providers
    app: object | None
    _shutdown_done: bool = field(default=False)

    def shutdown(self) -> None:
        """Flush and stop all three signal providers within a hard time budget.

        Idempotent, and never raises: this runs on the exit path, where an
        unreachable collector must cost a few seconds at most and a telemetry error
        must not become a non-zero exit status.
        """
        if self._shutdown_done:
            return
        self._shutdown_done = True
        per_signal = _SHUTDOWN_BUDGET_MS // 3
        for provider in (
            self.providers.tracer_provider,
            self.providers.meter_provider,
            self.providers.logger_provider,
        ):
            try:
                provider.force_flush(per_signal)
            except Exception as exc:
                _LOG.debug("force_flush failed during shutdown: %s", exc)
            try:
                provider.shutdown()
            except Exception as exc:
                _LOG.debug("provider shutdown failed: %s", exc)


def _is_otel_log_handler(handler: logging.Handler) -> bool:
    """Report whether `handler` is an OTel log handler, ours or a foreign one.

    The deprecated `opentelemetry.sdk._logs.LoggingHandler` is matched by module and
    class name rather than by isinstance, because importing it is banned (it raises
    a DeprecationWarning as of 1.44.0).
    """
    if isinstance(handler, LoggingHandler):
        return True
    cls = type(handler)
    return cls.__module__.startswith("opentelemetry") and "LoggingHandler" in cls.__name__


def _otel_formatter() -> structlog.stdlib.ProcessorFormatter:
    """Build the JSON formatter used for OTLP log bodies.

    Always JSON regardless of `log_format`: console rendering is for humans reading a
    terminal, and without any formatter the OTel handler falls back to
    `record.getMessage()`, which under the stdlib rewire is a Python dict repr.
    """
    return structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=_shared_processors(),
    )


def init(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    level: int | str | None = None,
    log_format: str | None = None,
    app: Any | None = None,
    sinks: Any | None = None,
) -> Telemetry:
    """
    Configure sanitized logging plus OTel logs, traces and metrics in one call.

    Precedence is explicit argument > env var > default. With no OTLP endpoint (or
    `OTEL_SDK_DISABLED=true`) everything still works in-process -- console logging,
    spans, meters and trace ids -- and nothing is exported, with one warning.

    Args:
        service_name: Service identity; falls back to OTEL_SERVICE_NAME.
        service_version: Reported as service.version when given.
        level: Log level; falls back to LOG_LEVEL, then INFO.
        log_format: "json" or "console"; falls back to LOG_FORMAT, then TTY detection.
        app: ASGI app to instrument for request spans and latency histograms.
        sinks: 0.3.x sinks to attach, as configure_logging accepts.

    Returns:
        The process-wide Telemetry handle. Calling init() again returns the same one.
    """
    global _STATE
    if _STATE is not None:
        warnings.warn(
            "penguin-utils init() already called; returning the existing handle",
            UserWarning,
            stacklevel=2,
        )
        return _STATE

    cfg = TelemetryConfig.resolve(
        service_name=service_name,
        service_version=service_version,
        level=level,
        log_format=log_format,
    )
    providers = build_providers(cfg, span_processor_factory=SanitizingSpanProcessorFactory)
    trace.set_tracer_provider(providers.tracer_provider)
    metrics.set_meter_provider(providers.meter_provider)
    set_logger_provider(providers.logger_provider)

    # Snapshot before configure_logging, which owns and therefore clears the root
    # handler set: under the opentelemetry-instrument auto-launcher the handler we
    # must not duplicate is already attached, and would otherwise be thrown away.
    root = logging.getLogger()
    preexisting = [h for h in root.handlers if _is_otel_log_handler(h)]

    configure_logging(
        level=cfg.level,
        json_output=(cfg.log_format == "json"),
        sinks=sinks,
    )
    root = logging.getLogger()

    if preexisting:
        _LOG.warning(
            "an OTel log handler was already installed; sanitizing it instead of "
            "adding a second one"
        )
        for handler in preexisting:
            handler.addFilter(SanitizingFilter())
            handler.addFilter(_ExcludeLoggers(_NOISY_LOGGER_PREFIXES))
            root.addHandler(handler)
    else:
        handler = SanitizingLogHandler(logger_provider=providers.logger_provider)
        handler.setLevel(cfg.level)
        handler.setFormatter(_otel_formatter())
        handler.addFilter(_ExcludeLoggers(_NOISY_LOGGER_PREFIXES))
        root.addHandler(handler)

    for noisy in _NOISY_LOGGER_PREFIXES:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    wrapped = _instrument_app(
        app=app,
        tracer_provider=providers.tracer_provider,
        meter_provider=providers.meter_provider,
    )

    _STATE = Telemetry(providers=providers, app=wrapped if app is not None else None)
    atexit.register(_STATE.shutdown)
    return _STATE


__all__: list[str] = ["Telemetry", "init"]
