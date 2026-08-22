# penguin-limiter

Rate limiting middleware for Penguin Tech Python applications.

## Features

- Flask extension with decorator-based route limiting
- Token bucket rate limiting algorithm
- In-process memory storage with LRU eviction
- Redis-backed storage for distributed systems
- Configurable rate limits (per second, minute, hour, day)
- Thread-safe implementation
- Standard HTTP rate limit headers

## Installation

```bash
pip install penguin-limiter

# With Redis support:
pip install 'penguin-limiter[redis]'
```

## Quick Start

```python
from flask import Flask
from penguin_limiter import FlaskRateLimiter, MemoryStorage, RateLimitConfig

app = Flask(__name__)

# Create rate limiter with 100 requests per hour
limiter = FlaskRateLimiter(
    config=RateLimitConfig.from_string("100/hour"),
    storage=MemoryStorage(),
)
limiter.init_app(app)


@app.route("/api/endpoint")
@limiter.limit()
def my_endpoint():
    return {"message": "success"}
```

## Configuration

### Using RateLimitConfig

```python
# Parse from string
config = RateLimitConfig.from_string("100/hour")

# Or create directly
from penguin_limiter import RateLimitConfig

config = RateLimitConfig(rate=100, unit="hour")
```

Supported units: `second`, `minute`, `hour`, `day`

### Storage Options

#### Memory Storage (Default)
```python
from penguin_limiter import MemoryStorage

storage = MemoryStorage(max_entries=10000)
```

#### Redis Storage
```python
from penguin_limiter import RedisStorage

storage = RedisStorage(url="redis://localhost:6379/0")
```

## API Reference

### FlaskRateLimiter

```python
limiter = FlaskRateLimiter(
    config=RateLimitConfig.from_string("100/hour"),
    storage=MemoryStorage(),
    key_func=lambda: request.remote_addr,  # Optional custom key function
)
```

### Decorating Routes

```python
# Use default limit
@app.route("/api/users")
@limiter.limit()
def get_users():
    return []


# Override limit for specific route
@app.route("/api/expensive")
@limiter.limit(RateLimitConfig.from_string("10/hour"))
def expensive_operation():
    return {}
```

### Rate Limit Headers

Standard X-RateLimit headers are added to all responses:
- `X-RateLimit-Limit`: Maximum requests in window
- `X-RateLimit-Remaining`: Requests remaining in current window
- `X-RateLimit-Reset`: Seconds until window resets
- `Retry-After`: Seconds to wait on 429 responses

## See Also

- Backend standards: `backend.md` Rate Limiting
- Flask extensions pattern: Similar to Flask-Security-Too, Flask-Limiter
