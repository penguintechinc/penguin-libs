# penguin-security

PenguinTech security utilities: sanitization, CSRF, password hashing (Argon2id),
rate limiting, validation, Pydantic integration, and cryptographic primitives
(`penguin_security.crypto` — formerly the standalone `penguin-crypto` package).

## Install

```bash
pip install penguin-security
```

## Quick Start

```python
from penguin_security import hash_password, verify_password
from penguin_security.crypto import encrypt, decrypt, generate_key
```
