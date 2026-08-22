"""penguin-libs — transition library.

All functionality has moved to focused packages. This package re-exports
everything for backwards compatibility. Install the focused package directly
for new projects.

Packages:
- penguin-security: Security utilities, including validation, pydantic
  integration, and crypto (penguin_security.validation, .pydantic, .crypto --
  formerly the standalone penguin-validation, penguin-pydantic, and
  penguin-crypto packages, all merged in)
"""

import penguin_libs._compat  # noqa: F401

__version__ = "0.3.0"

__all__ = ["__version__"]
