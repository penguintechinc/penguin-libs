"""Construct OTel Tracer/Meter/Logger providers and (optionally) OTLP exporters."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter

from .config import TelemetryConfig

_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class Providers:
    """OTel providers (tracer, meter, logger) with optional OTLP export.

    When exporting=True, OTLP exporters are attached and read OTEL_EXPORTER_OTLP_*
    env vars natively. When exporting=False, providers operate in-process only.
    """

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    exporting: bool


def _http() -> bool:
    """Check if OTEL_EXPORTER_OTLP_PROTOCOL is set to HTTP variant."""
    return os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").startswith("http")


def _exporters() -> tuple[SpanExporter, object, object]:
    """Instantiate protocol-specific OTLP exporters (span, metric, log).

    Exporters are created argument-free; they read OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_EXPORTER_OTLP_PROTOCOL, and signal-specific overrides natively per OTel spec.
    """
    if _http():
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter as HTTPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HTTPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPSpanExporter,
        )
        return HTTPSpanExporter(), HTTPMetricExporter(), HTTPLogExporter()
    else:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
            OTLPLogExporter as GrpcLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GrpcMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcSpanExporter,
        )
        return GrpcSpanExporter(), GrpcMetricExporter(), GrpcLogExporter()


def build_providers(
    cfg: TelemetryConfig,
    span_processor_factory: Callable[[SpanExporter], object] = BatchSpanProcessor,
) -> Providers:
    """Build OTel providers with optional OTLP export attachment.

    When cfg.otlp_endpoint is falsy or cfg.sdk_disabled is True, providers are
    created but no exporters are attached; exporting=False and a WARN is logged.
    cfg.otlp_endpoint gates whether exporters are attached, not where they point —
    exporters read OTEL_EXPORTER_OTLP_ENDPOINT natively at export time.
    """
    res_attrs = {"service.name": cfg.service_name}
    if cfg.service_version:
        res_attrs["service.version"] = cfg.service_version
    resource = Resource.create(res_attrs)
    exporting = bool(cfg.otlp_endpoint) and not cfg.sdk_disabled
    if not exporting:
        _LOG.warning(
            "OTLP endpoint unset or SDK disabled; telemetry stays in-process (not exported)"
        )
        tp = TracerProvider(resource=resource)
        mp = MeterProvider(resource=resource)
        lp = LoggerProvider(resource=resource)
        return Providers(tp, mp, lp, exporting=False)
    span_exp, metric_exp, log_exp = _exporters()
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(span_processor_factory(span_exp))  # type: ignore[arg-type]
    metric_reader = PeriodicExportingMetricReader(metric_exp)  # type: ignore[arg-type]
    mp = MeterProvider(resource=resource, metric_readers=[metric_reader])
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(log_exp))  # type: ignore[arg-type]
    return Providers(tp, mp, lp, exporting=True)
