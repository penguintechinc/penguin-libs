# penguin-security

PenguinTech security utilities.

## Install

```bash
pip install penguin-security
```

## Quick Start

```python
from penguin_security import ...
```

## Crypto (optional)

`penguin_security.crypto` provides symmetric/hybrid encryption, key
derivation (Argon2id, HKDF), ECC (X25519/Ed25519), hashing, and per-tenant
envelope encryption (`penguin_security.crypto.envelope`). It was formerly
the standalone `penguin-crypto` package.

These primitives depend on `cryptography` and `argon2-cffi`, which are
**not** installed with the base package. Install the `crypto` extra to use
them:

```bash
pip install "penguin-security[crypto]"
```

```python
from penguin_security.crypto import encrypt, decrypt, generate_key

key = generate_key()
ciphertext = encrypt(b"secret data", key)
plaintext = decrypt(ciphertext, key)
```

Importing `penguin_security.crypto` without the extra installed raises a
clear `ImportError` naming the extra.

`AwsKmsKek` (in `penguin_security.crypto.envelope`) additionally needs
`boto3`, kept as its own `aws` extra so the rest of the envelope module
never requires it:

```bash
pip install "penguin-security[crypto,aws]"
```
