"""Regression tests for lazy Flask imports and optional dependencies.

penguin_security shipped with a hard import-time dependency on Flask via
pydantic/flask_integration.py, even though Flask is not declared as a runtime
dependency. `import penguin_security` failed outright with a bare
ModuleNotFoundError for any consumer without Flask installed. Fixed with a PEP 562
module-level __getattr__ that defers the Flask import until one of the
Flask-dependent symbols is actually accessed (precedent: penguin_aaa 11c4e19).
"""

import sys

import pytest

_FLASK_INTEGRATION_NAMES = (
    "ValidationErrorResponse",
    "model_response",
    "validate_body",
    "validate_query_params",
    "validated_request",
)


def _reset_penguin_security_modules() -> None:
    """Force a fresh import of penguin_security and its submodules."""
    for mod in [key for key in sys.modules if key.startswith("penguin_security")]:
        del sys.modules[mod]


def test_import_penguin_security_without_flask() -> None:
    """penguin_security must import cleanly with Flask absent (regression)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "flask", None)
        _reset_penguin_security_modules()

        # This must NOT raise ModuleNotFoundError.
        import penguin_security

        # Core, non-Flask symbols remain accessible.
        assert hasattr(penguin_security, "ElderBaseModel")
        assert hasattr(penguin_security, "EmailStr")
        assert hasattr(penguin_security, "StrongPassword")
        assert hasattr(penguin_security, "hash_password")
        assert hasattr(penguin_security, "verify_password")
        assert hasattr(penguin_security, "generate_csrf_token")
        assert hasattr(penguin_security, "validate_csrf_token")
        assert hasattr(penguin_security, "check_rate_limit")
        assert hasattr(penguin_security, "sanitize_html")


def test_import_penguin_security_pydantic_without_flask() -> None:
    """penguin_security.pydantic must import cleanly with Flask absent (regression)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "flask", None)
        _reset_penguin_security_modules()

        import penguin_security.pydantic as pydantic_mod

        assert hasattr(pydantic_mod, "ElderBaseModel")
        assert hasattr(pydantic_mod, "RequestModel")


@pytest.mark.parametrize("name", _FLASK_INTEGRATION_NAMES)
def test_flask_symbol_missing_flask_raises_clear_error(name: str) -> None:
    """Accessing a Flask-dependent symbol without Flask raises a clear ImportError."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "flask", None)
        _reset_penguin_security_modules()

        import penguin_security

        with pytest.raises(
            ImportError,
            match=rf"{name} requires the 'flask' extra: pip install penguin-security\[flask\]",
        ):
            getattr(penguin_security, name)


@pytest.mark.parametrize("name", _FLASK_INTEGRATION_NAMES)
def test_flask_symbol_missing_flask_raises_clear_error_from_pydantic_submodule(
    name: str,
) -> None:
    """Same guarantee accessing the symbol via penguin_security.pydantic directly."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "flask", None)
        _reset_penguin_security_modules()

        import penguin_security.pydantic as pydantic_mod

        with pytest.raises(
            ImportError,
            match=rf"{name} requires the 'flask' extra: pip install penguin-security\[flask\]",
        ):
            getattr(pydantic_mod, name)


@pytest.mark.parametrize("name", _FLASK_INTEGRATION_NAMES)
def test_flask_symbol_usable_with_flask_installed(name: str) -> None:
    """Flask-dependent symbols work normally when Flask IS installed."""
    try:
        import flask  # noqa: F401
    except ImportError:
        pytest.skip("Flask not installed")

    import penguin_security

    assert callable(getattr(penguin_security, name))


def test_flask_symbols_remain_in_all() -> None:
    """Flask-dependent symbols stay in __all__ for discoverability."""
    import penguin_security

    for name in _FLASK_INTEGRATION_NAMES:
        assert name in penguin_security.__all__

    import penguin_security.pydantic as pydantic_mod

    for name in _FLASK_INTEGRATION_NAMES:
        assert name in pydantic_mod.__all__


def test_unknown_attribute_still_raises_attribute_error() -> None:
    """__getattr__ must not swallow genuinely missing attributes."""
    import penguin_security

    with pytest.raises(AttributeError):
        penguin_security.this_attribute_does_not_exist

    import penguin_security.pydantic as pydantic_mod

    with pytest.raises(AttributeError):
        pydantic_mod.this_attribute_does_not_exist
