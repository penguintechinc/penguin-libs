"""Tests for version management and OTel dependencies."""

from importlib import metadata

import penguintechinc_utils as u


def test_version_matches_installed_metadata() -> None:
    """Version should match the installed package metadata."""
    assert u.__version__ == metadata.version("penguin-utils")


def test_version_is_0_4_x() -> None:
    """Version should be 0.4.x."""
    assert u.__version__.startswith("0.4.")


def test_dotversion_file_agrees_with_pyproject() -> None:
    """`.version` must track pyproject's version, which is the single source.

    The version lived in three unsynced files before 0.4.0 (`.version` was stale at
    0.2.0.0). pyproject is authoritative; `.version` adds only a build epoch, so its
    first three components have to match or the two have drifted apart again.
    """
    import pathlib
    import tomllib

    package_root = pathlib.Path(__file__).parent.parent
    pyproject_version = tomllib.loads((package_root / "pyproject.toml").read_text())["project"][
        "version"
    ]
    dotversion = (package_root / ".version").read_text().strip()

    assert dotversion.startswith(pyproject_version), (
        f".version={dotversion!r} does not track pyproject version={pyproject_version!r}"
    )
    assert dotversion.split(".")[:3] == pyproject_version.split(".")[:3]


def test_otel_imports_are_available() -> None:
    """OTel packages should be available after install."""
    import opentelemetry.sdk._logs  # noqa: F401
    from opentelemetry.instrumentation.logging.handler import LoggingHandler  # noqa: F401

    assert LoggingHandler is not None
