# penguin-libs API Reference

## penguin_libs.flask

Flask response envelope and pagination helpers.

### success_response

```python
success_response(
    data: Any = None,
    message: str = "Success",
    status_code: int = 200,
    meta: dict | None = None,
) -> tuple[Response, int]
```

Returns a standardized Flask JSON success response.

**Response body:**
```json
{"status": "success", "data": ..., "message": "Success", "meta": {...}}
```

### error_response

```python
error_response(
    message: str,
    status_code: int = 400,
    **kwargs,
) -> tuple[Response, int]
```

Returns a standardized Flask JSON error response. Extra `kwargs` are merged into the body.

**Response body:**
```json
{"status": "error", "message": "Invalid email", "field": "email"}
```

### get_pagination_params

```python
get_pagination_params(default_per_page: int = 20) -> tuple[int, int]
```

Extracts `page` and `per_page` from `request.args`. Invalid or negative values are clamped to 1.

Returns `(page, per_page)`.

### paginate

```python
paginate(query_or_list: Any, page: int, per_page: int) -> dict
```

Paginates a SQLAlchemy query, penguin-dal Rows, or plain list.

**Returns:**
```python
{
    "items": [...],
    "page": 1,
    "per_page": 20,
    "total": 100,
    "pages": 5,
}
```

Supported inputs:
- **SQLAlchemy Query** — uses `.count()` + `.offset().limit()` (no full scan)
- **penguin-dal Rows / list-like** — sliced in Python
- **Plain Python list** — sliced directly

---

## penguin_libs.validation

### Validators

| Validator | Description |
|-----------|-------------|
| `IsEmail()` | Validates RFC-style email format |
| `IsURL()` | Validates URL format |
| `IsNotEmpty()` | Value must be non-empty string |
| `IsLength(min, max)` | String length constraint |
| `IsInSet(values)` | Value must be in the given set |
| `IsNumeric()` | Value must be numeric |
| `IsStrongPassword()` | Minimum strength password check |

### chain

```python
chain(*validators) -> Callable
```

Returns a combined validator that runs all validators in sequence. Raises `ValidationError` on first failure.

---

## penguin_libs.http

### HTTPClient

```python
HTTPClient(config: HTTPClientConfig)
```

Resilient HTTP client with retry logic and circuit breaker.

| Method | Description |
|--------|-------------|
| `client.get(url, **kwargs)` | GET request |
| `client.post(url, json=None, **kwargs)` | POST request |
| `client.put(url, json=None, **kwargs)` | PUT request |
| `client.delete(url, **kwargs)` | DELETE request |

### HTTPClientConfig

```python
HTTPClientConfig(
    timeout: float = 30.0,
    retry: RetryConfig | None = None,
    headers: dict | None = None,
)
```

### RetryConfig

```python
RetryConfig(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
)
```

---

## penguin_libs.grpc

### create_server

```python
create_server(interceptors: list | None = None, port: int = 50051) -> grpc.Server
```

### GrpcClient

```python
GrpcClient(address: str)
```

| Method | Description |
|--------|-------------|
| `client.channel()` | Context manager returning a gRPC channel |
| `client.call_with_retry(stub_method, request)` | Call with automatic retry |

### AuthInterceptor

```python
AuthInterceptor(secret_key: str)
```

gRPC server-side interceptor that validates JWT tokens in request metadata.

---

## penguin_libs.pydantic

### RequestModel

Pydantic `BaseModel` subclass with strict validation defaults.

### validated_request

```python
@validated_request(body_model: type[RequestModel])
```

Flask route decorator. Parses and validates the JSON request body against `body_model`. Injects the validated model as `body` kwarg.

### model_response

```python
model_response(model: BaseModel, status_code: int = 200) -> tuple[Response, int]
```

Serializes a Pydantic model to a Flask JSON response using `success_response`.
