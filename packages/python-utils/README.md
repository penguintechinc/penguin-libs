# penguin-utils

Sanitized structured logging **and** OpenTelemetry logs, traces and metrics for Python microservices, in one call. Automatically redacts PII (passwords, tokens, emails) before anything reaches a sink, a console, or an OTLP collector. Supports stdout, file, syslog, AWS CloudWatch, GCP Cloud Logging, and Apache Kafka.

OpenTelemetry is a required dependency, not an extra — there is no configuration to remember and no per-service boilerplate to copy.

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
from penguintechinc_utils import init, get_logger

tel = init()                  # zero-arg: everything from env
log = get_logger(__name__)

log.info("user login", email="user@example.com", password="secret123", remember_me=True)
# -> {"event": "user login", "email": "[email]", "password": "[REDACTED]",
#     "remember_me": true, "level": "info", "trace_id": "...", "span_id": "..."}
```

One `init()` gives you sanitized console logging, OTel log export, traces and
metrics. Add `app=` to instrument an ASGI app with request spans and a latency
histogram:

```python
tel = init(service_name="my-api", app=quart_app)
app = tel.app                 # the instrumented app to serve
```

### Logs only

`configure_logging()` stays logs-only and is unchanged from 0.3.x — use it when a
process should not set up telemetry at all:

```python
import logging
from penguintechinc_utils import configure_logging, get_logger

configure_logging(level=logging.INFO, json_output=True)
get_logger("worker").info("started")
```

### Sanitized logger (0.3.x style)

```python
from penguintechinc_utils import SanitizedLogger

logger = SanitizedLogger("MyComponent")
logger.info("User login attempt", {
    "email": "user@example.com",  # Logged as: [email]
    "password": "secret123",      # Logged as: [REDACTED]
    "remember_me": True,          # Logged as-is
})
```

## Configuration

Explicit argument > environment variable > default.

| `init()` arg | Env var | Default |
|---|---|---|
| `service_name` | `OTEL_SERVICE_NAME` | one WARN, then `unknown_service:<argv0>` |
| `service_version` | — | unset |
| `level` | `LOG_LEVEL` | `INFO` |
| `log_format` | `LOG_FORMAT` | `json` when stdout is not a TTY, else `console` |
| `app` | — | `None` |
| `sinks` | `LOG_CLOUDWATCH_*`, `LOG_GCP_*`, `LOG_KAFKA_*` | none |

The OTLP destination is never hardcoded — it comes from the standard
`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL` (`grpc` by default),
`OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_EXPORTER_OTLP_TIMEOUT`,
`OTEL_RESOURCE_ATTRIBUTES` and `OTEL_SDK_DISABLED` variables, read natively by the
SDK. Point the same build at SigNoz, Grafana, Datadog or any OTLP collector.

**With no endpoint set** (or `OTEL_SDK_DISABLED=true`) everything still works:
console logging, spans, meters and trace ids in log lines. Nothing is exported and
one warning is logged. Telemetry failure is never an application failure.

## Timing helpers

```python
from penguintechinc_utils import get_tracer, get_meter, timed

@timed("orders.checkout")          # span + orders.checkout.duration histogram (ms)
async def checkout(cart): ...

with timed("report.render"):
    render()
```

`timed` works as a decorator or context manager, on sync and `async def` alike.

## Behaviour changes in 0.4.0

1. **`level` is enforced.** DEBUG lines that printed regardless of configuration in
   0.3.x now require `LOG_LEVEL=DEBUG`.
2. **A failing sink no longer raises** into your log call, and no longer stops the
   other sinks from receiving the event.
3. **CloudWatch, GCP, Kafka and KillKrill deliver asynchronously**, behind a bounded
   queue that drops the oldest event when full. Stdout, file and callback sinks stay
   synchronous.

Every 0.3.x symbol keeps its name, signature and return type; an API-contract test
asserts this.

## Pre-fork servers

Call `init()` **in the worker**, not in the parent, so each worker gets its own
exporter threads:

```python
def post_fork(server, worker):   # gunicorn/hypercorn hook
    init(service_name="my-api")
```

## Auto-Configure Sinks from Environment

`configure_logging_from_env()` builds sinks from `LOG_CLOUDWATCH_*`, `LOG_GCP_*` and
`LOG_KAFKA_*`; pass them to `init()` (or `configure_logging()`), which attaches them:

```python
from penguintechinc_utils import get_logger, init
from penguintechinc_utils.logging import configure_logging_from_env

init(service_name="MyApp", sinks=configure_logging_from_env())
get_logger("MyApp").info("started")
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
