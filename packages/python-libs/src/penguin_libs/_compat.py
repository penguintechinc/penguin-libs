"""sys.modules aliases for backwards-compatible submodule imports."""

import sys

# Import split packages with graceful fallback
_PACKAGES = {}

_package_specs = [
    ("penguin_crypto", "penguin_libs.crypto"),
    ("penguin_security", "penguin_libs.security"),
    ("penguin_http", "penguin_libs.http"),
]

for pkg_name, legacy_name in _package_specs:
    try:
        _PACKAGES[pkg_name] = __import__(pkg_name)
        # Try to re-export everything from the submodule
        try:
            _mod = sys.modules[pkg_name]
            if hasattr(_mod, "__all__"):
                for _name in _mod.__all__:
                    globals()[_name] = getattr(_mod, _name)
        except Exception:
            pass  # Skip re-export if it fails
    except ImportError as _import_err:
        # Package not available; skip it
        # Note: silently skipping failed imports - this is intentional for optional split packages
        pass

__all__ = list(_PACKAGES.keys())

# Sub-package aliases for dissolved packages
# Allows legacy imports like: from penguin_libs.validation import X -> penguin_security.validation
_sub_aliases = [
    ("penguin_security.validation", "penguin_libs.validation"),
    ("penguin_security.pydantic", "penguin_libs.pydantic"),
    ("penguin_http.flask", "penguin_libs.flask"),
    ("penguin_http.grpc", "penguin_libs.grpc"),
    ("penguin_http.h3", "penguin_libs.h3"),
    # Also alias old package names for backwards compatibility
    ("penguin_security.validation", "penguin_validation"),
    ("penguin_security.pydantic", "penguin_pydantic"),
    ("penguin_http.flask", "penguin_flask"),
    ("penguin_http.grpc", "penguin_grpc"),
    ("penguin_http.h3", "penguin_h3"),
]
for new_name, alias in _sub_aliases:
    if new_name in sys.modules and alias not in sys.modules:
        sys.modules[alias] = sys.modules[new_name]

# Register sys.modules aliases for backwards-compatible submodule imports
# Allows: from penguin_libs.crypto import ... (legacy) -> from penguin_crypto import ... (new)
for pkg_name, legacy_name in _package_specs:
    if pkg_name in _PACKAGES:
        _module = _PACKAGES[pkg_name]
        if legacy_name not in sys.modules:
            sys.modules[legacy_name] = _module
