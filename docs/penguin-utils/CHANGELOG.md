# penguin-utils Changelog

## 0.2.0 (2026-03-10)

### New Features

- **CloudWatchSink**: AWS CloudWatch Logs backend with batched `PutLogEvents` and automatic sequence token management
- **GCPCloudLoggingSink**: Google Cloud Logging backend with structured JSON payloads
- **KafkaSink**: Apache Kafka backend with JSON-encoded messages and `flush()` support
- **`configure_logging_from_env()`**: Build sinks automatically from environment variables — detects CloudWatch, GCP, and Kafka configuration
- Optional install extras: `[cloudwatch]`, `[gcp]`, `[kafka]`

## 0.1.0

- Initial release
- `SanitizedLogger` with automatic PII redaction
- Built-in sinks: `StdoutSink`, `FileSink`, `SyslogSink`, `CallbackSink`
- Sanitization rules for passwords, tokens, emails, session IDs, MFA codes
