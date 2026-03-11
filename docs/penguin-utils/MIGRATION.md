# penguin-utils Migration Guide

## Migrating to 0.2.0

No breaking changes. The 0.2.0 release adds cloud sink backends as optional extras and the `configure_logging_from_env()` helper.

### Adding Cloud Sinks

Install the extras you need:

```bash
pip install penguin-utils[cloudwatch]
pip install penguin-utils[gcp]
pip install penguin-utils[kafka]
```

Set the corresponding environment variables:

```bash
# CloudWatch
LOG_CLOUDWATCH_GROUP=/myapp/production
LOG_CLOUDWATCH_STREAM=api-server

# GCP
LOG_GCP_PROJECT=my-gcp-project
LOG_GCP_LOG_NAME=myapp-api

# Kafka
LOG_KAFKA_SERVERS=broker1:9092,broker2:9092
LOG_KAFKA_TOPIC=app-logs
```

Then use `configure_logging_from_env()` instead of manually constructing sinks:

**Before (0.1.x):**
```python
from penguintechinc_utils import SanitizedLogger
from penguintechinc_utils.sinks import StdoutSink

logger = SanitizedLogger("MyApp", sinks=[StdoutSink()])
```

**After (0.2.x) — auto-detects cloud sinks from env:**
```python
from penguintechinc_utils.logging import configure_logging_from_env
from penguintechinc_utils import SanitizedLogger

logger = SanitizedLogger("MyApp", sinks=configure_logging_from_env())
```

`StdoutSink` is always included. Cloud sinks are added when their required env vars are present.
