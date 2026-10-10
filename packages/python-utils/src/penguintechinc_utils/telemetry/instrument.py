"""Optional auto-instrumentation for ASGI apps and common client libraries.

Wraps an ASGI app in `OpenTelemetryMiddleware` when one is given, and
best-effort instruments httpx, SQLAlchemy, and redis if those libraries
happen to be installed. Every hook here is optional: a missing dependency
or a raising instrumentor is logged at DEBUG and never propagates, so
telemetry setup can never break application startup.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Protocol

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

_LOG = logging.getLogger(__name__)

_CONDITIONAL_INSTRUMENTORS: tuple[tuple[str, str], ...] = (
    ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    ("opentelemetry.instrumentation.sqlalchemy", "SQLAlchemyInstrumentor"),
    ("opentelemetry.instrumentation.redis", "RedisInstrumentor"),
)


class ASGIApp(Protocol):
    """Structural type for an ASGI 3 application callable (app or middleware)."""

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None: ...


def instrument(
    app: ASGIApp | None = None,
    *,
    tracer_provider: TracerProvider,
    meter_provider: MeterProvider,
) -> ASGIApp | None:
    """Wrap `app` in OTel ASGI middleware and instrument optional client libs.

    Returns the wrapped app when `app` is given (or the original app if
    wrapping itself fails, since dropping the app entirely would break
    service startup), else returns None. httpx/SQLAlchemy/redis
    instrumentation is attempted opportunistically and independently of
    each other and of the ASGI wrap.
    """
    wrapped: ASGIApp | None = app
    if app is not None:
        try:
            from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

            wrapped = OpenTelemetryMiddleware(
                app,
                tracer_provider=tracer_provider,
                meter_provider=meter_provider,
            )
        except Exception as exc:
            _LOG.debug("ASGI instrumentation unavailable, using unwrapped app: %s", exc)

    for module_name, class_name in _CONDITIONAL_INSTRUMENTORS:
        _instrument_optional(module_name, class_name, tracer_provider)

    return wrapped


def _instrument_optional(
    module_name: str, class_name: str, tracer_provider: TracerProvider
) -> None:
    """Best-effort instrument one optional client library by module/class name.

    Isolated per-call so an unimportable module or a raising instrumentor
    (e.g. double-instrumentation in a misbehaving library) never prevents
    the remaining instrumentors from running or bubbles up to the caller.
    """
    try:
        module = import_module(module_name)
        instrumentor_cls = getattr(module, class_name)
        instrumentor_cls().instrument(tracer_provider=tracer_provider)
    except Exception as exc:
        _LOG.debug("%s instrumentation skipped: %s", module_name, exc)
