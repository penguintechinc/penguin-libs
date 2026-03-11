# penguin-utils

Sanitized structured logging for Python microservices. Automatically redacts PII fields (email, password, token, etc.) before writing to any output sink. Supports stdout, file, syslog, AWS CloudWatch, GCP Cloud Logging, and Apache Kafka backends.

## Installation

```bash
pip install penguin-utils

# Optional cloud backends:
pip install penguin-utils[cloudwatch]   # AWS CloudWatch Logs (boto3)
pip install penguin-utils[gcp]          # Google Cloud Logging
pip install penguin-utils[kafka]        # Apache Kafka (kafka-python)
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

## Built-in Sinks

| Sink | Description | Install extra |
|------|-------------|---------------|
| `StdoutSink` | JSON/text to stdout | (included) |
| `FileSink` | Rotating log files | (included) |
| `SyslogSink` | UDP syslog | (included) |
| `CallbackSink` | Custom callback | (included) |
| `CloudWatchSink` | AWS CloudWatch Logs | `[cloudwatch]` |
| `GCPCloudLoggingSink` | Google Cloud Logging | `[gcp]` |
| `KafkaSink` | Apache Kafka topic | `[kafka]` |

## Auto-Configure from Environment Variables

```python
from penguintechinc_utils.logging import configure_logging_from_env
from penguintechinc_utils import SanitizedLogger

sinks = configure_logging_from_env()
logger = SanitizedLogger("MyApp", sinks=sinks)
```

Environment variables read: `LOG_CLOUDWATCH_GROUP`, `LOG_CLOUDWATCH_STREAM`, `LOG_GCP_PROJECT`, `LOG_GCP_LOG_NAME`, `LOG_KAFKA_SERVERS`, `LOG_KAFKA_TOPIC`.

📚 Full documentation: [docs/penguin-utils/](../../docs/penguin-utils/)
