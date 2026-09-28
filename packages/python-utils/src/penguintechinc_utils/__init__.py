"""
Penguin Tech Python Utilities

Shared utilities for Penguin Tech Python applications.
"""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("penguin-utils")
except _metadata.PackageNotFoundError:  # running from source tree without install
    __version__ = "0.4.0"

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
    AsyncSink,
    CallbackSink,
    CloudWatchSink,
    FileSink,
    GCPCloudLoggingSink,
    KafkaSink,
    Sink,
    StdoutSink,
    SyslogSink,
)

# Imported last: telemetry reaches back into .logging, so .logging must be fully
# initialised before this runs.
from .telemetry import Telemetry, init
from .telemetry.helpers import get_meter, get_tracer, timed

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
    "AsyncSink",
    # killkrill
    "KillKrillConfig",
    "KillKrillSink",
    # telemetry
    "init",
    "Telemetry",
    "get_tracer",
    "get_meter",
    "timed",
]
