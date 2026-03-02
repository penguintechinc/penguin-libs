"""
Penguin Tech Python Utilities

Shared utilities for Penguin Tech Python applications.
"""

__version__ = "0.1.0"

from .killkrill import KillKrillConfig, KillKrillSink
from .logging import SanitizedLogger, configure_logging, get_logger, sanitize_log_data
from .sinks import CallbackSink, FileSink, Sink, StdoutSink, SyslogSink

__all__ = [
    "__version__",
    # logging
    "configure_logging",
    "get_logger",
    "sanitize_log_data",
    "SanitizedLogger",
    # sinks
    "Sink",
    "StdoutSink",
    "FileSink",
    "SyslogSink",
    "CallbackSink",
    # killkrill
    "KillKrillConfig",
    "KillKrillSink",
]
