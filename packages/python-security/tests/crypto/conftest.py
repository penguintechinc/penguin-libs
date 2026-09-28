"""Skip the crypto test subtree entirely when the `crypto` extra isn't installed.

`penguin_security.crypto` requires `cryptography` and `argon2-cffi`, which are
not base-package dependencies (see `penguin-security[crypto]`). Without this
guard, a base-only install would fail test *collection* (not just a skip) the
moment pytest tries to import these modules, breaking the rest of the suite.
"""

import pytest

pytest.importorskip(
    "cryptography", reason="requires the 'crypto' extra: pip install 'penguin-security[crypto]'"
)
pytest.importorskip(
    "argon2", reason="requires the 'crypto' extra: pip install 'penguin-security[crypto]'"
)
