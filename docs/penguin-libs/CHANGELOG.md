# penguin-libs Changelog

## 0.2.0 (2026-03-10)

### New Features

- **`penguin_libs.flask` submodule**: Flask response envelope and pagination helpers
  - `success_response(data, message, status_code, meta)` — standard JSON success envelope
  - `error_response(message, status_code, **kwargs)` — standard JSON error envelope
  - `get_pagination_params(default_per_page)` — extract `page`/`per_page` from `request.args`
  - `paginate(query_or_list, page, per_page)` — paginate SQLAlchemy queries, penguin-dal Rows, or lists
- New `[flask]` install extra

## 0.1.0

- Initial release
- `penguin_libs.validation` — PyDAL-style validators (string, numeric, network, datetime, password)
- `penguin_libs.grpc` — gRPC server/client helpers and `AuthInterceptor`
- `penguin_libs.http` — `HTTPClient` with retry logic and circuit breaker
- `penguin_libs.pydantic` — `RequestModel`, `validated_request`, `model_response`, `EmailStr`, `StrongPassword`
- `penguin_libs.crypto` — Cryptographic utilities
- `penguin_libs.security` — Security helpers
