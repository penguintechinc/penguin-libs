"""Regression tests for lazy imports and optional dependencies (gh-70)."""

import sys
from unittest.mock import patch

import pytest


def test_import_penguin_aaa_without_flask() -> None:
    """Test that penguin_aaa can be imported without Flask installed (regression: gh-70)."""
    # Block Flask import to simulate it not being installed
    with patch.dict(sys.modules, {"flask": None}):
        # Remove penguin_aaa from sys.modules to force a fresh import
        modules_to_remove = [key for key in sys.modules if key.startswith("penguin_aaa")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # This should NOT raise ModuleNotFoundError
        import penguin_aaa

        # Core symbols should be accessible without Flask
        assert hasattr(penguin_aaa, "OIDCProvider")
        assert hasattr(penguin_aaa, "OIDCRelyingParty")
        assert hasattr(penguin_aaa, "Claims")
        assert hasattr(penguin_aaa, "TokenSet")
        assert hasattr(penguin_aaa, "MemoryKeyStore")
        assert hasattr(penguin_aaa, "TokenStore")


def test_create_oidc_blueprint_missing_flask() -> None:
    """Test that accessing create_oidc_blueprint raises error without Flask (gh-70)."""
    # Block Flask import to simulate it not being installed
    with patch.dict(sys.modules, {"flask": None}):
        # Remove penguin_aaa from sys.modules to force a fresh import
        modules_to_remove = [key for key in sys.modules if key.startswith("penguin_aaa")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        import penguin_aaa

        # Accessing create_oidc_blueprint should raise ImportError with clear message
        with pytest.raises(
            ImportError,
            match=r"create_oidc_blueprint requires the 'flask' extra",
        ):
            # Attribute access triggers lazy __getattr__, which raises.
            penguin_aaa.create_oidc_blueprint  # noqa: B018


def test_create_oidc_blueprint_with_flask() -> None:
    """Test that create_oidc_blueprint is accessible when Flask is installed (gh-70)."""
    try:
        import flask  # noqa: F401

        import penguin_aaa

        # Should be able to access create_oidc_blueprint
        assert callable(penguin_aaa.create_oidc_blueprint)
    except ImportError:
        pytest.skip("Flask not installed")


def test_create_oidc_blueprint_in_all() -> None:
    """Test that create_oidc_blueprint is listed in __all__ for discoverability."""
    import penguin_aaa

    assert "create_oidc_blueprint" in penguin_aaa.__all__
