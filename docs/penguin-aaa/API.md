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
