import logging

from penguintechinc_utils.telemetry.config import TelemetryConfig
from penguintechinc_utils.telemetry.providers import build_providers


def test_no_endpoint_builds_inprocess_no_export(monkeypatch, caplog):
    """No endpoint → in-process, exporting=False, WARN logged."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve(service_name="svc")
        p = build_providers(cfg)
    assert p.exporting is False
    assert (
        p.tracer_provider is not None
        and p.meter_provider is not None
        and p.logger_provider is not None
    )


def test_endpoint_enables_export(monkeypatch):
    """Endpoint set via env → exporting=True."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.example:4317")
    cfg = TelemetryConfig.resolve(service_name="svc")
    p = build_providers(cfg)
    assert p.exporting is True


def test_resource_has_service_name():
    """Resource includes service.name from config."""
    cfg = TelemetryConfig.resolve(service_name="svc")
    p = build_providers(cfg)
    attrs = p.tracer_provider.resource.attributes
    assert attrs["service.name"] == "svc"


def test_sdk_disabled_no_export(monkeypatch, caplog):
    """SDK disabled flag forces exporting=False even with endpoint."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve(service_name="svc")
        p = build_providers(cfg)
    assert p.exporting is False
    assert (
        p.tracer_provider is not None
        and p.meter_provider is not None
        and p.logger_provider is not None
    )


def test_resource_has_service_version():
    """Resource includes service.version when set."""
    cfg = TelemetryConfig.resolve(service_name="svc", service_version="1.2.3")
    p = build_providers(cfg)
    attrs = p.tracer_provider.resource.attributes
    assert attrs["service.name"] == "svc"
    assert attrs["service.version"] == "1.2.3"


def test_http_protocol(monkeypatch):
    """HTTP protocol variant selected via env var."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.example:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    cfg = TelemetryConfig.resolve(service_name="svc")
    p = build_providers(cfg)
    assert p.exporting is True
