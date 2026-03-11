# penguin-libs

Core Python utilities for Penguin Tech Inc services. Provides HTTP client helpers, validation, Pydantic base models, gRPC utilities, cryptography, security utilities, and Flask response/pagination helpers.

## Installation

```bash
pip install penguin-libs

# With extras:
pip install penguin-libs[flask]   # Flask response and pagination helpers
pip install penguin-libs[grpc]    # gRPC client/server utilities
pip install penguin-libs[http]    # HTTP client with retry/circuit breaker
pip install penguin-libs[all]     # All extras
```

## Modules

| Module | Description |
|--------|-------------|
| `penguin_libs.validation` | PyDAL-style input validators with Pydantic integration |
| `penguin_libs.http` | HTTP client with retry logic and circuit breaker |
| `penguin_libs.grpc` | gRPC server/client helpers and security interceptors |
| `penguin_libs.pydantic` | Base models and Flask integration |
| `penguin_libs.crypto` | Cryptographic utilities |
| `penguin_libs.security` | Security helpers |
| `penguin_libs.flask` | Flask response envelope and pagination helpers |

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

config = HTTPClientConfig(timeout=30.0, retry=RetryConfig(max_retries=3))
client = HTTPClient(config)
response = client.get("https://api.example.com/users")
```

📚 Full documentation: [docs/penguin-libs/](../../docs/penguin-libs/)
