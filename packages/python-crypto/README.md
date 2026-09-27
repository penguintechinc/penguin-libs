# penguin-crypto

PenguinTech cryptographic utilities: symmetric/hybrid/ECC primitives plus
per-tenant envelope encryption (AES-256-GCM field encryption, KMS DEK
wrap/unwrap providers, a bounded/epoch-checked DEK cache, and HKDF blind
indexes) per the Waddles v3 tenant-envelope-encryption design.

## Install

```bash
pip install penguin-crypto

# With AWS KMS support:
pip install "penguin-crypto[aws]"
```

## Quick Start

```python
from penguin_crypto import encrypt, decrypt, generate_key
```

### Envelope encryption

```python
import os

from penguin_crypto.envelope import (
    build_aad,
    envelope_encrypt,
    envelope_decrypt,
    LocalSecretKek,
    DekCache,
)

# 1. Wrap/unwrap a tenant DEK under a KEK (dev/alpha: LocalSecretKek;
#    production: AwsKmsKek or your own KekProvider).
kek = LocalSecretKek(key_path="/var/run/secrets/kek")
dek = os.urandom(32)
wrapped_dek = kek.wrap(dek)          # store this in tenant_encryption_keys
unwrapped = kek.unwrap(wrapped_dek)  # after a cache miss

# 2. Cache unwrapped DEKs, bounded + TTL + epoch-checked.
cache = DekCache(epoch_source=lambda tenant_id: get_rotation_epoch(tenant_id))
cache.put(tenant_id, dek_version, unwrapped)

# 3. Encrypt/decrypt a field, bound to its exact tenant/table/column/row.
aad = build_aad(
    tenant_id=tenant_id,
    table="hub_chat_messages",
    column="message_content",
    row_uuid=row_uuid,
    dek_version=dek_version,
)
envelope = envelope_encrypt(plaintext, unwrapped, dek_version=dek_version, aad=aad)
plaintext = envelope_decrypt(envelope, unwrapped, aad=aad)
```

See the `penguin_crypto.envelope` module docstrings for the KMS provider
interface, the per-DEK encryption-count rotation cap, and the blind-index
equality-lookup helper (`penguin_crypto.envelope.blind_index`).
