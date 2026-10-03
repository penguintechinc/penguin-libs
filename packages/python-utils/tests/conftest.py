"""Shared pytest fixtures for the penguin-utils suite.

`configure_logging()` reconfigures process-global state (root-logger handlers and
structlog's config), so without a restore between tests one test's handlers --
bound to pytest's temporary captured stdout/stderr -- would still be attached
when a later test logs, writing to a closed stream.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog


@pytest.fixture(autouse=True)
def restore_global_logging_state() -> Iterator[None]:
    """Snapshot root-logger handlers/level and structlog config; restore after each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_structlog: dict[str, Any] = structlog.get_config()
    try:
        yield
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        structlog.configure(**saved_structlog)
