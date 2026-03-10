# penguin-libs

Core Python utilities for Penguin Tech Inc services: HTTP client, validation, Pydantic base models, gRPC helpers, cryptography, security utilities, and Flask response/pagination helpers.

## Installation

```bash
pip install penguin-libs

# With extras:
pip install penguin-libs[flask]   # Flask response envelope and pagination
pip install penguin-libs[grpc]    # gRPC client/server utilities
pip install penguin-libs[http]    # HTTP client with retry/circuit breaker
pip install penguin-libs[all]     # All extras
```

## Quick Start

### Flask Helpers

```python
from penguin_libs.flask import success_response, error_response, paginate, get_pagination_params

@app.route("/api/v1/users")
def list_users():
    page, per_page = get_pagination_params()
    users = db(db.users.active == True).select()
    data = paginate(users, page, per_page)
    return success_response(data=data["items"], meta=data)
```

### Validation

```python
from penguin_libs.validation import IsEmail, IsLength, chain

validators = chain(IsNotEmpty(), IsLength(3, 255), IsEmail())
result = validators("user@example.com")
```

### HTTP Client

```python
from penguin_libs.http import HTTPClient, HTTPClientConfig, RetryConfig

client = HTTPClient(HTTPClientConfig(
    timeout=30.0,
    retry=RetryConfig(max_retries=3),
))
response = client.get("https://api.example.com/users")
```

📚 **Full documentation**: [docs/penguin-libs/](../../docs/penguin-libs/)
- [README](../../docs/penguin-libs/README.md) — complete module overview
- [API Reference](../../docs/penguin-libs/API.md) — all classes and methods
- [Changelog](../../docs/penguin-libs/CHANGELOG.md)
- [Migration Guide](../../docs/penguin-libs/MIGRATION.md) — adopting Flask helpers in 0.2.x

## License

AGPL-3.0 — See [LICENSE](../../LICENSE) for details.
