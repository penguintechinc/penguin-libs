"""Penguin Tech Python Utilities

Shared utilities for Penguin Tech Python applications.
"""

__version__ = "0.3.0"

from .decorators import (
    DecoratorContext,
    DecoratorRegistry,
    DynamicDecorator,
    add_decorator,
    create_decorator,
    decorator_factory,
)
from .killkrill import KillKrillConfig, KillKrillSink
from .logging import (
    SanitizedLogger,
    configure_logging,
    configure_logging_from_env,
    get_logger,
    sanitize_log_data,
)
from .sinks import (
    CallbackSink,
    CloudWatchSink,
    FileSink,
    GCPCloudLoggingSink,
    KafkaSink,
    Sink,
    StdoutSink,
    SyslogSink,
)

__all__ = [
    "__version__",
    # decorators
    "add_decorator",
    "create_decorator",
    "decorator_factory",
    "DecoratorContext",
    "DynamicDecorator",
    "DecoratorRegistry",
    # logging
    "configure_logging",
    "configure_logging_from_env",
    "get_logger",
    "sanitize_log_data",
    "SanitizedLogger",
    # sinks
    "Sink",
    "StdoutSink",
    "FileSink",
    "SyslogSink",
    "CallbackSink",
    "CloudWatchSink",
    "GCPCloudLoggingSink",
    "KafkaSink",
    # killkrill
    "KillKrillConfig",
    "KillKrillSink",
]
