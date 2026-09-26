import logging
import pytest
from penguintechinc_utils.telemetry.config import TelemetryConfig


def test_arg_beats_env(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    cfg = TelemetryConfig.resolve(service_name="from-arg")
    assert cfg.service_name == "from-arg"


def test_env_level_parsed(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert TelemetryConfig.resolve(service_name="s").level == logging.DEBUG


def test_bad_env_level_warns_and_defaults(monkeypatch, caplog):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve(service_name="s")
    assert cfg.level == logging.INFO
    assert any("LOG_LEVEL" in r.message for r in caplog.records)


def test_bad_arg_level_raises():
    with pytest.raises((ValueError, TypeError)):
        TelemetryConfig.resolve(service_name="s", level="verbose")


def test_missing_service_name_warns_and_falls_back(monkeypatch, caplog):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve()
    assert cfg.service_name.startswith("unknown_service")
