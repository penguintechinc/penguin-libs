# penguin-aaa

Authentication, Authorization, and Audit library for Python. Provides OIDC provider and relying party implementations, RBAC with OIDC-style scope-based permissions, SPIFFE/SPIRE integration, tenant isolation, and cryptographic key management.

## Installation

```bash
pip install penguin-aaa
```

## Quick Start

### OIDC Relying Party (Flask app consuming tokens)

```python
from penguin_aaa import OIDCRelyingParty

rp = OIDCRelyingParty(
    issuer="https://auth.example.com",
    client_id="my-app",
    client_secret="secret",
)

# Validate an incoming JWT
claims = rp.validate_token(token)
# claims.sub, claims.scope, claims.tenant, claims.teams
```

### OIDC Provider (issuing tokens)

```python
from penguin_aaa import OIDCProvider

provider = OIDCProvider(
    issuer="https://auth.example.com",
    keystore=FileKeyStore("/etc/auth/keys"),
)

token = provider.issue_token(
    sub="user-uuid",
    scope="users:read reports:write",
    tenant="tenant-id",
)
```

### Key Store

```python
from penguin_aaa import MemoryKeyStore, FileKeyStore

# In-memory (development/testing)
ks = MemoryKeyStore()

# File-backed (production)
ks = FileKeyStore("/etc/auth/keys")
```

## Modules

| Module | Description |
|--------|-------------|
| `penguin_aaa.authn` | OIDC provider and relying party |
| `penguin_aaa.authz` | RBAC, scope enforcement, tenant isolation |
| `penguin_aaa.audit` | Audit logging for auth events |
| `penguin_aaa.crypto` | Key store and JWT signing |
| `penguin_aaa.middleware` | Flask/ASGI middleware for token validation |
| `penguin_aaa.hardening` | Security hardening utilities |

📚 Full documentation: [docs/penguin-aaa/](../../docs/penguin-aaa/)
