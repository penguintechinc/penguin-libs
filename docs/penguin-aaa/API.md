# penguin-aaa API Reference

## Claims

```python
@dataclass(slots=True)
class Claims:
    sub: str
    iss: str
    aud: list[str]
    iat: int
    exp: int
    scope: str
    tenant: str
    teams: list[str]
    roles: list[str]
```

## TokenSet

```python
@dataclass(slots=True)
class TokenSet:
    access_token: str
    id_token: str | None
    refresh_token: str | None
    expires_in: int
    token_type: str
```

## OIDCRelyingParty

```python
OIDCRelyingParty(
    issuer: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
)
```

| Method | Description |
|--------|-------------|
| `rp.validate_token(token: str) -> Claims` | Validate and decode a JWT, returns `Claims` |
| `rp.exchange_code(code: str, redirect_uri: str) -> TokenSet` | Exchange auth code for tokens |
| `rp.refresh(refresh_token: str) -> TokenSet` | Refresh access token |

## OIDCProvider

```python
OIDCProvider(issuer: str, keystore: KeyStore)
```

| Method | Description |
|--------|-------------|
| `provider.issue_token(sub, scope, tenant, **claims) -> str` | Issue a signed JWT |
| `provider.revoke_token(jti: str)` | Revoke a token by JTI |

## KeyStore

Abstract base. Implementations: `MemoryKeyStore`, `FileKeyStore`.

| Method | Description |
|--------|-------------|
| `ks.get_signing_key() -> Key` | Get current signing key |
| `ks.get_verification_keys() -> list[Key]` | Get all verification keys (for key rotation) |
| `ks.rotate()` | Generate and store a new signing key |

## Middleware

### Flask

```python
from penguin_aaa.middleware import require_scope

@app.route("/api/v1/users")
@require_scope("users:read")
def list_users():
    ...
```

### ASGI

```python
from penguin_aaa.middleware import AuthMiddleware

app = AuthMiddleware(
    app=your_asgi_app,
    issuer="https://auth.example.com",
    public_paths={"/health", "/api/v1/status"},
)
```

## Secrets (`penguin_aaa.secrets`, optional `[secrets]` extra)

Formerly `penguin-sal` (packages/python-secrets); import path moved from
`penguin_sal.X` to `penguin_aaa.secrets.X`, public API unchanged.

### `penguin_aaa.secrets.adapters`

| Function | Description |
|--------|-------------|
| `get_adapter_class(scheme: str) -> type[BaseAdapter]` | Lazily import and return the adapter class for a URI scheme (`vault`, `aws-sm`, `gcp-sm`, `azure-kv`, `oci-vault`, `k8s`, `1password`, `passbolt`, `doppler`, `infisical`, `cyberark`). Raises `InvalidURIError` for an unknown scheme, `AdapterNotInstalledError` naming the missing `[secrets-*]` extra if the backend SDK isn't installed. |
| `list_backends() -> list[str]` | Sorted list of all supported backend scheme names. |

### `penguin_aaa.secrets.core.base_adapter.BaseAdapter`

Abstract base every backend adapter implements: `authenticate()`, `get(key, version=None) -> Secret`,
`set(key, value, metadata=None) -> Secret`, `delete(key) -> bool`, `list(prefix="", limit=None) -> SecretList`,
`exists(key) -> bool`, `health_check() -> bool`, `close()`. Supports use as a context manager.

### `penguin_aaa.secrets.core.types`

```python
@dataclass(slots=True)
class Secret:
    key: str
    value: str | bytes | dict[str, Any]
    version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] | None = None

@dataclass(slots=True)
class SecretList:
    keys: list[str]
    cursor: str | None = None

@dataclass(slots=True)
class ConnectionConfig:
    scheme: str
    host: str
    port: int | None = None
    path: str = ""
    username: str | None = None
    password: str | None = None
    params: dict[str, str] = field(default_factory=dict)
```

### `penguin_aaa.secrets.core.exceptions`

| Exception | Raised when |
|--------|-------------|
| `PySecretsError` | Base class for all secrets errors |
| `ConnectionError` | Failed to connect to the backend |
| `AuthenticationError` | Authentication with the backend failed |
| `AuthorizationError` | Insufficient permissions |
| `SecretNotFoundError` | The requested secret does not exist |
| `InvalidURIError` | Malformed or unsupported connection URI |
| `BackendError` | Backend request failed |
| `AdapterNotInstalledError` | Backend SDK not installed; message names the `[secrets-*]` extra to install |
