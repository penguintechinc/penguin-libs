"""Per-tenant envelope encryption primitives.

Implements the AES-256-GCM field-encryption scheme from the Waddles v3
tenant-envelope-encryption design: a canonical AAD builder that binds
ciphertext to its tenant/table/column/row/key-version context, a versioned
ciphertext format, a DEK-wrapping KMS provider interface (with a local
dev/alpha provider and stubs for cloud KMS providers), a bounded DEK cache
with epoch-based invalidation, and an HKDF-derived blind-index helper for
equality-only search over encrypted columns.
"""

from .aad import build_aad
from .blind_index import blind_index, derive_blind_index_key
from .cache import DekCache, DekCacheEntry
from .cipher import (
    CiphertextFormatError,
    EncryptionCounter,
    InMemoryEncryptionCounter,
    RotationRequiredError,
    envelope_decrypt,
    envelope_dek_version,
    envelope_encrypt,
)
from .kek import (
    AwsKmsKek,
    AzureKeyVaultKek,
    GcpKmsKek,
    KekProvider,
    LocalSecretKek,
    VaultTransitKek,
)

__all__ = [
    # AAD
    "build_aad",
    # Cipher
    "envelope_encrypt",
    "envelope_decrypt",
    "envelope_dek_version",
    "CiphertextFormatError",
    "RotationRequiredError",
    "EncryptionCounter",
    "InMemoryEncryptionCounter",
    # KEK providers
    "KekProvider",
    "LocalSecretKek",
    "AwsKmsKek",
    "GcpKmsKek",
    "AzureKeyVaultKek",
    "VaultTransitKek",
    # DEK cache
    "DekCache",
    "DekCacheEntry",
    # Blind index
    "derive_blind_index_key",
    "blind_index",
]
