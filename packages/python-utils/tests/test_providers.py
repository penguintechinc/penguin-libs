import logging
from penguintechinc_utils.telemetry.config import TelemetryConfig
from penguintechinc_utils.telemetry.providers import build_providers


def _cfg(**kw):
    base = dict(service_name="svc", service_version=None, level=logging.INFO,
                log_format="json", otlp_endpoint=None, sdk_disabled=False)
    base.update(kw); return TelemetryConfig(**base)


def test_no_endpoint_builds_inprocess_no_export(caplog):
    with caplog.at_level(logging.WARNING):
        p = build_providers(_cfg(otlp_endpoint=None))
    assert p.exporting is False
    assert p.tracer_provider is not None and p.meter_provider is not None and p.logger_provider is not None


def test_endpoint_enables_export():
    p = build_providers(_cfg(otlp_endpoint="http://localhost:4317"))
    assert p.exporting is True


def test_resource_has_service_name():
    p = build_providers(_cfg(service_name="svc"))
    attrs = p.tracer_provider.resource.attributes
    assert attrs["service.name"] == "svc"


def test_sdk_disabled_no_export(caplog):
    with caplog.at_level(logging.WARNING):
        p = build_providers(_cfg(sdk_disabled=True, otlp_endpoint="http://localhost:4317"))
    assert p.exporting is False
    assert p.tracer_provider is not None and p.meter_provider is not None and p.logger_provider is not None


def test_resource_has_service_version():
    p = build_providers(_cfg(service_name="svc", service_version="1.2.3"))
    attrs = p.tracer_provider.resource.attributes
    assert attrs["service.name"] == "svc"
    assert attrs["service.version"] == "1.2.3"


def test_http_protocol(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    p = build_providers(_cfg(otlp_endpoint="http://localhost:4318"))
    assert p.exporting is True
