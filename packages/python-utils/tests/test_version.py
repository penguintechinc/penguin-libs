"""Tests for version management and OTel dependencies."""

from importlib import metadata

import penguintechinc_utils as u


def test_version_matches_installed_metadata() -> None:
    """Version should match the installed package metadata."""
    assert u.__version__ == metadata.version("penguin-utils")


def test_version_is_0_4_x() -> None:
    """Version should be 0.4.x."""
    assert u.__version__.startswith("0.4.")


def test_otel_imports_are_available() -> None:
    """OTel packages should be available after install."""
    import opentelemetry.sdk._logs  # noqa: F401
    from opentelemetry.instrumentation.logging.handler import LoggingHandler  # noqa: F401

    assert LoggingHandler is not None
