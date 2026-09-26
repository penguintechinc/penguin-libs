"""Resolve telemetry configuration from explicit args, then env, then defaults."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

_LOG = logging.getLogger(__name__)


def _resolve_level(level, env_val) -> int:
    if level is not None:
        if isinstance(level, int):
            return level
        parsed = logging.getLevelName(str(level).upper())
        if not isinstance(parsed, int):
            raise ValueError(f"invalid level argument: {level!r}")
        return parsed
    if env_val:
        parsed = logging.getLevelName(env_val.upper())
        if isinstance(parsed, int):
            return parsed
        _LOG.warning("ignoring invalid LOG_LEVEL=%r; defaulting to INFO", env_val)
    return logging.INFO


@dataclass(slots=True)
class TelemetryConfig:
    service_name: str
    service_version: str | None
    level: int
    log_format: str
    otlp_endpoint: str | None
    sdk_disabled: bool

    @classmethod
    def resolve(
        cls,
        *,
        service_name=None,
        service_version=None,
        level=None,
        log_format=None,
    ) -> TelemetryConfig:
        name = service_name or os.getenv("OTEL_SERVICE_NAME")
        if not name:
            name = f"unknown_service:{os.path.basename(sys.argv[0]) or 'python'}"
            _LOG.warning("no service_name/OTEL_SERVICE_NAME set; using %r", name)
        fmt = (
            log_format
            or os.getenv("LOG_FORMAT")
            or ("console" if sys.stdout.isatty() else "json")
        )
        if fmt not in ("json", "console"):
            if log_format is not None:
                raise ValueError(f"invalid log_format argument: {log_format!r}")
            _LOG.warning(
                "ignoring invalid LOG_FORMAT=%r; defaulting to json", fmt
            )
            fmt = "json"
        return cls(
            service_name=name,
            service_version=service_version,
            level=_resolve_level(level, os.getenv("LOG_LEVEL")),
            log_format=fmt,
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            sdk_disabled=os.getenv("OTEL_SDK_DISABLED", "").lower() == "true",
        )
