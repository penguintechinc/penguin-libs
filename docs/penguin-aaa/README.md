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

### Secrets Management (optional, `[secrets]` extra)

Unified secrets-backend adapters (Vault, AWS/GCP/Azure/OCI, Kubernetes, 1Password,
Passbolt, Doppler, Infisical, CyberArk Conjur) — formerly the standalone
`penguin-sal` package, now shipped as `penguin_aaa.secrets`.

```bash
# All backends
pip install "penguin-aaa[secrets]"

# Or just the one you need, e.g. Vault only
pip install "penguin-aaa[secrets-vault]"
```

```python
from penguin_aaa.secrets.adapters import get_adapter_class
from penguin_aaa.secrets.core.types import ConnectionConfig

VaultAdapter = get_adapter_class("vault")
adapter = VaultAdapter(
    ConnectionConfig(scheme="https", host="vault.example.com", port=8200, password="s.xxxx")
)
secret = adapter.get("myapp/db_pass")
print(secret.value)
```

The base `penguin-aaa` install pulls in zero secrets-backend dependencies. Calling
`get_adapter_class(...)` for a backend whose SDK isn't installed raises
`AdapterNotInstalledError`, naming the exact extra to install (e.g.
`penguin-aaa[secrets-vault]`).

> **Migrating from `penguin-sal` / `penguin_secrets`?** Replace `penguin_sal.X`
> imports with `penguin_aaa.secrets.X` (e.g. `penguin_sal.adapters.vault` →
> `penguin_aaa.secrets.adapters.vault`, `penguin_sal.core.types` →
> `penguin_aaa.secrets.core.types`). The public API is unchanged, only the
> import path and install extras moved. `penguin-secrets` is superseded and no
> longer published — see `packages/python-secrets/README.md`.

## Modules

| Module | Description |
|--------|-------------|
| `penguin_aaa.authn` | OIDC provider and relying party |
| `penguin_aaa.authz` | RBAC, scope enforcement, tenant isolation |
| `penguin_aaa.audit` | Audit logging for auth events |
| `penguin_aaa.crypto` | Key store and JWT signing |
| `penguin_aaa.middleware` | Flask/ASGI middleware for token validation |
| `penguin_aaa.hardening` | Security hardening utilities |
| `penguin_aaa.secrets` | Secrets backend adapters (optional, `[secrets]` extra) |

📚 Full documentation: [docs/penguin-aaa/](../../docs/penguin-aaa/)
