"""Construct OTel Tracer/Meter/Logger providers and (optionally) OTLP exporters."""
from __future__ import annotations
import logging, os
from dataclasses import dataclass
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from .config import TelemetryConfig

_LOG = logging.getLogger(__name__)

@dataclass(slots=True)
class Providers:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    exporting: bool

def _http() -> bool:
    return os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").startswith("http")

def _exporters():
    if _http():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    return OTLPSpanExporter(), OTLPMetricExporter(), OTLPLogExporter()

def build_providers(cfg: TelemetryConfig, span_processor_factory=BatchSpanProcessor) -> Providers:
    res_attrs = {"service.name": cfg.service_name}
    if cfg.service_version:
        res_attrs["service.version"] = cfg.service_version
    resource = Resource.create(res_attrs)
    exporting = bool(cfg.otlp_endpoint) and not cfg.sdk_disabled
    if not exporting:
        _LOG.warning("OTLP endpoint unset or SDK disabled; telemetry stays in-process (not exported)")
        tp = TracerProvider(resource=resource)
        mp = MeterProvider(resource=resource)
        lp = LoggerProvider(resource=resource)
        return Providers(tp, mp, lp, exporting=False)
    span_exp, metric_exp, log_exp = _exporters()
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(span_processor_factory(span_exp))
    mp = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(metric_exp)])
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(log_exp))
    return Providers(tp, mp, lp, exporting=True)
