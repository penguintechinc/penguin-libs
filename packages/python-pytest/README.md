# penguin-pytest

Shared pytest fixtures and test helpers for PenguinTech Python packages.

## Installation

```bash
pip install penguin-pytest           # base (ASGI + gRPC helpers only)
pip install "penguin-pytest[dal]"    # include DAL fixtures
pip install "penguin-pytest[flask]"  # include Flask fixtures
pip install "penguin-pytest[dal,flask]"  # all extras
```

## Modules

| Module | Exports |
|--------|---------|
| `penguin_pytest.asgi` | `asgi_http_scope`, `asgi_send_collector`, `asgi_ok_app` |
| `penguin_pytest.grpc` | `mock_grpc_module` (fixture), `grpc_handler_call_details` |
| `penguin_pytest.dal` | `sqlite_engine`, `users_posts_engine`, `dal_db` (fixtures) |
| `penguin_pytest.flask` | `flask_app`, `flask_client` (fixtures) |

## Quick Start

```python
# conftest.py
pytest_plugins = ["penguin_pytest.asgi", "penguin_pytest.flask"]

# test_my_middleware.py
from penguin_pytest.asgi import asgi_http_scope, asgi_send_collector, asgi_ok_app

async def test_my_middleware():
    scope = asgi_http_scope(path="/api/v1/resource")
    messages, send = asgi_send_collector()
    await my_middleware(asgi_ok_app(), scope, None, send)
    assert messages[0]["status"] == 200
```
