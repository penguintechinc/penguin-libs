# penguin-utils

Sanitized structured logging for Python microservices. Automatically redacts PII (passwords, tokens, emails) before writing to any output sink. Supports stdout, file, syslog, AWS CloudWatch, GCP Cloud Logging, and Apache Kafka.

## Installation

```bash
pip install penguin-utils

# Optional cloud backends:
pip install penguin-utils[cloudwatch]   # AWS CloudWatch Logs
pip install penguin-utils[gcp]          # Google Cloud Logging
pip install penguin-utils[kafka]        # Apache Kafka
```

## Quick Start

```python
from penguintechinc_utils import SanitizedLogger
from penguintechinc_utils.sinks import StdoutSink

logger = SanitizedLogger("MyComponent", sinks=[StdoutSink()])

logger.info("User login attempt", {
    "email": "user@example.com",  # Logged as: [email]@example.com
    "password": "secret123",       # Logged as: [REDACTED]
    "remember_me": True,           # Logged as-is
})
```

## Auto-Configure from Environment

```python
from penguintechinc_utils.logging import configure_logging_from_env
from penguintechinc_utils import SanitizedLogger

logger = SanitizedLogger("MyApp", sinks=configure_logging_from_env())
```

## Dynamic Decorator Builder

Eliminates traditional 3-tier function boilerplate for Python decorators.

```python
from penguintechinc_utils import add_decorator

@add_decorator(name="my-cool-decorator")
def my_cool_decorator(ctx):
    print(f"Calling {ctx.func.__name__} with decorator args: {ctx.dec_kwargs}")
    ctx.execution_time = 0
    return ctx.proceed()

# Use with or without parameters on sync or async functions:
@my_cool_decorator(tag="v1")
def process_data(item):
    return item.upper()
```

📚 **Full documentation**: [docs/penguin-utils/](../../docs/penguin-utils/)
- [README](../../docs/penguin-utils/README.md) — complete feature overview and all sinks
- [API Reference](../../docs/penguin-utils/API.md) — all classes and methods
- [Changelog](../../docs/penguin-utils/CHANGELOG.md)
- [Migration Guide](../../docs/penguin-utils/MIGRATION.md) — upgrading to 0.2.x cloud sinks

## License

MIT — See [LICENSE](../../LICENSE) for details.
