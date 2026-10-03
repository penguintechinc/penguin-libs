"""The 0.3.x public API must survive 0.4.0 unchanged, name for name and arg for arg.

Consumers (gough, license-server, elder, penguincloud) pin no shims: a renamed symbol
or a reordered parameter is a broken install, not a deprecation.
"""

from __future__ import annotations

import inspect

import penguintechinc_utils as u

# Every symbol 0.3.x exported that a consumer could be importing.
_V03X_SYMBOLS = (
    "configure_logging",
    "configure_logging_from_env",
    "get_logger",
    "sanitize_log_data",
    "SanitizedLogger",
    "Sink",
    "StdoutSink",
    "FileSink",
    "SyslogSink",
    "CallbackSink",
    "CloudWatchSink",
    "GCPCloudLoggingSink",
    "KafkaSink",
    "KillKrillSink",
    "KillKrillConfig",
    "decorator_factory",
    "create_decorator",
    "add_decorator",
    "DecoratorContext",
    "DecoratorRegistry",
    "DynamicDecorator",
    "__version__",
)

_NEW_SYMBOLS = ("init", "Telemetry", "get_tracer", "get_meter", "timed")


def test_03x_symbols_present() -> None:
    """No 0.3.x name may disappear."""
    missing = [name for name in _V03X_SYMBOLS if not hasattr(u, name)]
    assert not missing, f"0.3.x symbols missing: {missing}"


def test_new_symbols_present() -> None:
    """The 0.4.0 additions are exported at the top level."""
    missing = [name for name in _NEW_SYMBOLS if not hasattr(u, name)]
    assert not missing, f"new symbols missing: {missing}"


def test_all_lists_every_checked_symbol() -> None:
    """__all__ must actually advertise what the tests above rely on."""
    undeclared = [n for n in (*_V03X_SYMBOLS, *_NEW_SYMBOLS) if n not in u.__all__]
    assert not undeclared, f"exported but not in __all__: {undeclared}"


def test_configure_logging_signature_unchanged() -> None:
    """Parameter names and order are part of the published contract."""
    assert list(inspect.signature(u.configure_logging).parameters) == [
        "level",
        "json_output",
        "sinks",
    ]


def test_sanitize_log_data_signature_unchanged() -> None:
    """sanitize_log_data(data) -> dict, exactly as 0.3.x."""
    assert list(inspect.signature(u.sanitize_log_data).parameters) == ["data"]
    assert u.sanitize_log_data({"secret": "s"})["secret"] == "[REDACTED]"


def test_sanitized_logger_signature_unchanged() -> None:
    """SanitizedLogger(name, level) and its five level methods all survive."""
    params = list(inspect.signature(u.SanitizedLogger.__init__).parameters)
    assert params == ["self", "name", "level"]
    for method in ("debug", "info", "warning", "error", "critical"):
        assert callable(getattr(u.SanitizedLogger, method))


def test_get_logger_accepts_its_03x_call_shapes() -> None:
    """Every documented get_logger call shape still works.

    The `level` default moved from INFO to None so configure_logging's level can
    actually take effect, which is a deliberate behaviour change -- but no call
    shape a consumer writes may stop working.
    """
    import logging

    assert u.get_logger("svc") is not None
    assert u.get_logger("svc", logging.DEBUG) is not None
    assert u.get_logger("svc", level=logging.DEBUG) is not None
    assert u.get_logger(name="svc") is not None


def test_configure_logging_from_env_returns_a_list() -> None:
    """Still returns a list of sinks, not None, with no env configured."""
    assert isinstance(u.configure_logging_from_env(), list)


def test_init_signature_is_keyword_only() -> None:
    """init() takes keyword arguments only, so adding parameters stays compatible."""
    params = inspect.signature(u.init).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    assert set(params) == {
        "service_name",
        "service_version",
        "level",
        "log_format",
        "app",
        "sinks",
    }


def test_version_matches_package_metadata() -> None:
    """__version__ is single-sourced from package metadata."""
    from importlib import metadata

    assert u.__version__ == metadata.version("penguin-utils")
