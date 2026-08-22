"""sys.modules aliases for backwards-compatible submodule imports."""

import logging
import sys

_logger = logging.getLogger(__name__)

# Import split packages with graceful fallback
_PACKAGES = {}

_package_specs = [
    ("penguin_security", "penguin_libs.security"),
]

for pkg_name, _legacy_name in _package_specs:
    try:
        _PACKAGES[pkg_name] = __import__(pkg_name)
        # Try to re-export everything from the submodule
        try:
            _mod = sys.modules[pkg_name]
            if hasattr(_mod, "__all__"):
                for _name in _mod.__all__:
                    globals()[_name] = getattr(_mod, _name)
        except Exception:
            _logger.debug(
                "Skipping re-export for %s; submodule attrs unavailable", pkg_name, exc_info=True
            )
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
    # penguin-crypto was merged into penguin-security as a crypto/ subpackage
    # (see PACKAGE_PUBLISHING_STATUS.md "Merged Packages"); alias both its
    # penguin_libs-transition path and its old standalone package name.
    ("penguin_security.crypto", "penguin_libs.crypto"),
    # Also alias old package names for backwards compatibility
    ("penguin_security.validation", "penguin_validation"),
    ("penguin_security.pydantic", "penguin_pydantic"),
    ("penguin_security.crypto", "penguin_crypto"),
]
for new_name, alias in _sub_aliases:
    if new_name in sys.modules and alias not in sys.modules:
        sys.modules[alias] = sys.modules[new_name]

# Register sys.modules aliases for backwards-compatible submodule imports
# Allows: from penguin_libs.security import ... (legacy) -> from penguin_security import ... (new)
for pkg_name, legacy_name in _package_specs:
    if pkg_name in _PACKAGES:
        _module = _PACKAGES[pkg_name]
        if legacy_name not in sys.modules:
            sys.modules[legacy_name] = _module
