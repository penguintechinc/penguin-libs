# Penguin Tech Python Libraries

Shared Python libraries for Penguin Tech applications.

## Installation

```bash
pip install penguin-libs

# With all extras
pip install penguin-libs[all]

# With specific extras
pip install penguin-libs[flask]
pip install penguin-libs[grpc]
pip install penguin-libs[http]
```

## Features

### Validation

PyDAL-style input validators with Pydantic integration:

```python
from penguin_libs.validation import IsEmail, IsLength, chain
from penguin_libs.pydantic import EmailStr, StrongPassword

# Direct validation
validator = IsEmail()
result = validator("user@example.com")

# Chained validators
validators = chain(IsNotEmpty(), IsLength(3, 255), IsEmail())
result = validators("user@example.com")

# Pydantic models
from pydantic import BaseModel

class User(BaseModel):
    email: EmailStr
    password: StrongPassword
```

### gRPC

Server helpers, client utilities, and security interceptors:

```python
from penguin_libs.grpc import create_server, GrpcClient, AuthInterceptor

# Server
interceptors = [AuthInterceptor(secret_key="your-secret")]
server = create_server(interceptors=interceptors)

# Client
client = GrpcClient('localhost:50051')
with client.channel() as channel:
    stub = MyServiceStub(channel)
    response = client.call_with_retry(stub.MyMethod, request)
```

### HTTP

Resilient HTTP client with retry logic and circuit breaker:

```python
from penguin_libs.http import HTTPClient, HTTPClientConfig, RetryConfig

config = HTTPClientConfig(
    timeout=30.0,
    retry=RetryConfig(max_retries=3, base_delay=1.0)
)
client = HTTPClient(config)
response = client.get("https://api.example.com/users")
```

### Pydantic Integration

Base models and Flask integration:

```python
from penguin_libs.pydantic import (
    RequestModel,
    validated_request,
    model_response,
)

class CreateUserRequest(RequestModel):
    name: str
    email: EmailStr

@app.route('/users', methods=['POST'])
@validated_request(body_model=CreateUserRequest)
def create_user(body: CreateUserRequest):
    return model_response(UserResponse(...))
```

## Modules

- **validation**: PyDAL-style validators (string, numeric, network, datetime, password)
- **grpc**: gRPC server/client helpers and security interceptors
- **http**: HTTP client with retries, circuit breaker, correlation ID
- **pydantic**: Base models, Flask integration, custom Annotated types
- **crypto**: Cryptographic utilities (placeholder)
- **security**: Security utilities (placeholder)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src tests
ruff check src tests

# Type check
mypy src
```

## License

AGPL-3.0 - See [LICENSE](../../LICENSE) for details.
