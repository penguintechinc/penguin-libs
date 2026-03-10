# penguin-utils API Reference

## SanitizedLogger

```python
SanitizedLogger(name: str, sinks: list[Sink], level: str = "info")
```

Structured logger that redacts PII before passing events to sinks.

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `debug` | `debug(msg, data=None)` | Log at DEBUG level |
| `info` | `info(msg, data=None)` | Log at INFO level |
| `warning` | `warning(msg, data=None)` | Log at WARNING level |
| `error` | `error(msg, data=None)` | Log at ERROR level |
| `critical` | `critical(msg, data=None)` | Log at CRITICAL level |

`data` is a dict of key/value pairs. Fields matching known PII keys are redacted before passing to sinks.

### Sanitization Rules

Automatically redacted fields (case-insensitive key matching):
- `password`, `passwd`, `secret`, `token`, `api_key`, `auth_token`, `refresh_token`
- `mfa_code`, `totp_code`, `otp`, `session_id`, `cookie`
- `email` — logged as `[email]@domain.com` (domain only)

## Sink Protocol

All sinks accept log event dicts. Custom sinks can be created by implementing:

```python
class MySink:
    def __call__(self, logger, method: str, event_dict: dict) -> dict:
        # Process and forward event_dict
        ...
        return event_dict
```

## Built-in Sinks

### StdoutSink

```python
StdoutSink(format: str = "json")
```

Writes JSON (default) or text-formatted log lines to stdout.

### FileSink

```python
FileSink(path: str, max_bytes: int = 10_485_760, backup_count: int = 5)
```

Rotating file sink. Creates `path` and up to `backup_count` rotation files.

### SyslogSink

```python
SyslogSink(host: str = "localhost", port: int = 514)
```

UDP syslog sink.

### CallbackSink

```python
CallbackSink(callback: Callable[[dict], None])
```

Invokes `callback(event_dict)` for each log event. Useful for testing.

## Cloud Sinks

### CloudWatchSink

```python
CloudWatchSink(
    log_group: str,
    log_stream: str,
    region: str = "us-east-1",
    batch_size: int = 100,
)
```

Buffers events and sends them to AWS CloudWatch Logs via `PutLogEvents`. Manages sequence tokens automatically.

**Methods:**
- `flush()` — Force-sends all buffered events immediately.

**Install:** `pip install penguin-utils[cloudwatch]`

### GCPCloudLoggingSink

```python
GCPCloudLoggingSink(project_id: str, log_name: str)
```

Sends structured JSON payloads to Google Cloud Logging.

**Install:** `pip install penguin-utils[gcp]`

### KafkaSink

```python
KafkaSink(bootstrap_servers: str, topic: str)
```

Publishes JSON-encoded log events to a Kafka topic. `bootstrap_servers` is a comma-separated list of `host:port` pairs.

**Methods:**
- `flush()` — Flush pending Kafka producer messages.

**Install:** `pip install penguin-utils[kafka]`

## configure_logging_from_env

```python
configure_logging_from_env() -> list[Sink]
```

Reads environment variables and returns a list of configured sinks. Always includes `StdoutSink`. Cloud sinks are added when their required env vars are present.

| Variable | Sink triggered |
|----------|---------------|
| `LOG_CLOUDWATCH_GROUP` + `LOG_CLOUDWATCH_STREAM` | `CloudWatchSink` |
| `LOG_GCP_PROJECT` + `LOG_GCP_LOG_NAME` | `GCPCloudLoggingSink` |
| `LOG_KAFKA_SERVERS` + `LOG_KAFKA_TOPIC` | `KafkaSink` |
