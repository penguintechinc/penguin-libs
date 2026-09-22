//! The single `tracing_subscriber::Layer` that both renders stdout JSON and
//! emits OTel log records, from the *same* sanitized field map.
//!
//! `opentelemetry-appender-tracing`'s bridge converts `tracing` fields to
//! OTel attributes with its own visitor, with no sanitization hook -- using
//! it directly would let secrets reach OTel Logs even if stdout were
//! sanitized separately. This layer computes
//! [`crate::sanitize::sanitize_object`] exactly once per event and is the
//! *only* thing that writes stdout or calls the OTel `Logger`, so both
//! outputs are guaranteed to see the same redacted data -- this is why
//! `opentelemetry-appender-tracing` is not a dependency of this crate.

use std::io::Write as _;

use opentelemetry::logs::{AnyValue, LogRecord as _, Logger as _, Severity};
use opentelemetry::Key;
use opentelemetry_sdk::logs::SdkLogger;
use serde_json::{Map, Value};
use tracing::field::{Field, Visit};
use tracing::{Event, Level, Subscriber};
use tracing_subscriber::fmt::format::Writer;
use tracing_subscriber::fmt::time::{FormatTime, SystemTime as FmtSystemTime};
use tracing_subscriber::layer::Context;
use tracing_subscriber::registry::LookupSpan;
use tracing_subscriber::Layer;

/// The well-known `tracing` field name carrying the formatted message
/// (`tracing::info!("text")` records it under this name).
const MESSAGE_FIELD: &str = "message";

/// Renders the current wall-clock time the same way
/// `tracing_subscriber::fmt`'s default `SystemTime` formatter does (RFC
/// 3339-ish), without pulling in a `chrono`/`time` dependency just for one
/// timestamp field.
fn iso_timestamp_now() -> String {
    let mut buf = String::new();
    let mut writer = Writer::new(&mut buf);
    // `FormatTime::format_time` for `SystemTime` only ever `write!`s into an
    // in-memory `String`, which cannot fail -- there is no fallible I/O
    // here, so a formatting error would mean tracing_subscriber itself is
    // broken, not a condition this crate needs to propagate.
    let _ = FmtSystemTime.format_time(&mut writer);
    buf
}

/// Maps a `tracing::Level` to the OTel log severity number/text pair.
fn otel_severity(level: &Level) -> (Severity, &'static str) {
    match *level {
        Level::ERROR => (Severity::Error, "ERROR"),
        Level::WARN => (Severity::Warn, "WARN"),
        Level::INFO => (Severity::Info, "INFO"),
        Level::DEBUG => (Severity::Debug, "DEBUG"),
        Level::TRACE => (Severity::Trace, "TRACE"),
    }
}

/// Converts one sanitized `serde_json::Value` into the `AnyValue` shape OTel
/// log attributes use. `Value::Null` has no `AnyValue` equivalent, so it is
/// rendered as the literal string `"null"` rather than being dropped --
/// dropping would make a redacted-to-null field indistinguishable from a
/// field that was never sent.
fn value_to_any_value(value: Value) -> AnyValue {
    match value {
        Value::Null => AnyValue::String("null".into()),
        Value::Bool(b) => AnyValue::Boolean(b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                AnyValue::Int(i)
            } else {
                AnyValue::Double(n.as_f64().unwrap_or_default())
            }
        }
        Value::String(s) => AnyValue::String(s.into()),
        Value::Array(items) => AnyValue::from_iter(items.into_iter().map(value_to_any_value)),
        Value::Object(map) => AnyValue::from_iter(
            map.into_iter()
                .map(|(k, v)| (Key::from(k), value_to_any_value(v))),
        ),
    }
}

/// Collects one `tracing::Event`'s fields into a JSON object, keyed by
/// field name, so the whole event can be sanitized as a unit.
#[derive(Default)]
struct FieldCollector {
    fields: Map<String, Value>,
}

impl Visit for FieldCollector {
    fn record_f64(&mut self, field: &Field, value: f64) {
        if let Some(n) = serde_json::Number::from_f64(value) {
            self.fields
                .insert(field.name().to_string(), Value::Number(n));
        }
    }

    fn record_i64(&mut self, field: &Field, value: i64) {
        self.fields
            .insert(field.name().to_string(), Value::from(value));
    }

    fn record_u64(&mut self, field: &Field, value: u64) {
        self.fields
            .insert(field.name().to_string(), Value::from(value));
    }

    fn record_bool(&mut self, field: &Field, value: bool) {
        self.fields
            .insert(field.name().to_string(), Value::Bool(value));
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        self.fields
            .insert(field.name().to_string(), Value::String(value.to_string()));
    }

    fn record_debug(&mut self, field: &Field, value: &dyn std::fmt::Debug) {
        self.fields.insert(
            field.name().to_string(),
            Value::String(format!("{value:?}")),
        );
    }
}

/// The layer installed by [`crate::telemetry::init`]. Renders one sanitized
/// JSON line per event to stdout, and -- when an OTel logger is configured
/// (i.e. `OTEL_EXPORTER_OTLP_ENDPOINT` was set) -- emits a matching
/// sanitized OTel `LogRecord`, correlated to the active span's trace
/// context by `tracing-opentelemetry` (see [`crate::telemetry::init`]'s
/// layer ordering).
pub struct SanitizingLayer {
    otel_logger: Option<SdkLogger>,
}

impl SanitizingLayer {
    /// Builds the layer. `otel_logger` is `None` when no OTLP endpoint is
    /// configured, in which case only the stdout JSON line is emitted.
    pub(crate) fn new(otel_logger: Option<SdkLogger>) -> Self {
        Self { otel_logger }
    }

    fn write_stdout(&self, level: &Level, target: &str, sanitized: &Map<String, Value>) {
        let mut line = Map::with_capacity(sanitized.len() + 3);
        line.insert("timestamp".to_string(), Value::String(iso_timestamp_now()));
        line.insert("level".to_string(), Value::String(level.to_string()));
        line.insert("target".to_string(), Value::String(target.to_string()));
        for (key, value) in sanitized {
            line.insert(key.clone(), value.clone());
        }
        // A dead/broken stdout must never crash the service -- see
        // rules/critical-rules.md Observability ("A dead exporter never
        // breaks the app"), which this crate extends to the stdout sink
        // too. There is nothing actionable to do with a stdout write
        // failure inside the logger itself.
        let mut stdout = std::io::stdout().lock();
        let _ = writeln!(stdout, "{}", Value::Object(line));
    }

    fn emit_otel(&self, level: &Level, target: &str, sanitized: &Map<String, Value>) {
        let Some(logger) = &self.otel_logger else {
            return;
        };
        let (severity, severity_text) = otel_severity(level);
        let mut record = logger.create_log_record();
        record.set_timestamp(std::time::SystemTime::now());
        record.set_observed_timestamp(std::time::SystemTime::now());
        record.set_severity_number(severity);
        record.set_severity_text(severity_text);
        record.set_target(target.to_string());
        if let Some(Value::String(message)) = sanitized.get(MESSAGE_FIELD) {
            record.set_body(AnyValue::String(message.clone().into()));
        }
        let attributes: Vec<(Key, AnyValue)> = sanitized
            .iter()
            .filter(|(key, _)| key.as_str() != MESSAGE_FIELD)
            .map(|(key, value)| (Key::from(key.clone()), value_to_any_value(value.clone())))
            .collect();
        record.add_attributes(attributes);
        logger.emit(record);
    }
}

impl<S> Layer<S> for SanitizingLayer
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
        let mut collector = FieldCollector::default();
        event.record(&mut collector);
        let sanitized = crate::sanitize::sanitize_object(&collector.fields);

        let metadata = event.metadata();
        self.write_stdout(metadata.level(), metadata.target(), &sanitized);
        self.emit_otel(metadata.level(), metadata.target(), &sanitized);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry::logs::LoggerProvider as _;
    use opentelemetry_sdk::logs::{InMemoryLogExporter, SdkLoggerProvider};
    use tracing_subscriber::layer::SubscriberExt as _;

    fn logged_bodies_and_attrs(exporter: &InMemoryLogExporter) -> Vec<String> {
        exporter
            .get_emitted_logs()
            .expect("in-memory exporter never fails")
            .into_iter()
            .map(|log| format!("{:?}", log.record))
            .collect()
    }

    #[test]
    fn debug_level_event_with_secret_field_is_redacted_in_otel_log() {
        let exporter = InMemoryLogExporter::default();
        let provider = SdkLoggerProvider::builder()
            .with_simple_exporter(exporter.clone())
            .build();
        let logger = provider.logger("penguin-logging-test");
        let layer = SanitizingLayer::new(Some(logger));
        let subscriber = tracing_subscriber::registry().with(layer);

        const SECRET: &str = "sk-live-do-not-leak-me";
        tracing::subscriber::with_default(subscriber, || {
            tracing::debug!(password = SECRET, "login attempt");
        });

        let rendered = logged_bodies_and_attrs(&exporter);
        assert_eq!(rendered.len(), 1, "expected exactly one emitted log record");
        assert!(
            !rendered[0].contains(SECRET),
            "secret leaked into an OTel log record at DEBUG: {}",
            rendered[0]
        );
        assert!(
            rendered[0].contains("REDACTED"),
            "expected the redaction marker in the emitted record: {}",
            rendered[0]
        );

        let _ = provider.shutdown();
    }

    #[test]
    fn non_sensitive_debug_field_survives_untouched() {
        let exporter = InMemoryLogExporter::default();
        let provider = SdkLoggerProvider::builder()
            .with_simple_exporter(exporter.clone())
            .build();
        let logger = provider.logger("penguin-logging-test");
        let layer = SanitizingLayer::new(Some(logger));
        let subscriber = tracing_subscriber::registry().with(layer);

        tracing::subscriber::with_default(subscriber, || {
            tracing::debug!(stage = "process", "bundle loaded");
        });

        let rendered = logged_bodies_and_attrs(&exporter);
        assert_eq!(rendered.len(), 1);
        assert!(rendered[0].contains("process"));

        let _ = provider.shutdown();
    }

    #[test]
    fn every_level_redacts_the_same_secret() {
        for level_call in ["error", "warn", "info", "debug", "trace"] {
            let exporter = InMemoryLogExporter::default();
            let provider = SdkLoggerProvider::builder()
                .with_simple_exporter(exporter.clone())
                .build();
            let logger = provider.logger("penguin-logging-test");
            let layer = SanitizingLayer::new(Some(logger));
            let subscriber = tracing_subscriber::registry().with(layer);

            const SECRET: &str = "hunter2-super-secret";
            tracing::subscriber::with_default(subscriber, || match level_call {
                "error" => tracing::error!(api_key = SECRET, "call failed"),
                "warn" => tracing::warn!(api_key = SECRET, "degraded"),
                "info" => tracing::info!(api_key = SECRET, "lifecycle"),
                "debug" => tracing::debug!(api_key = SECRET, "decision point"),
                _ => tracing::trace!(api_key = SECRET, "fine-grained"),
            });

            let rendered = logged_bodies_and_attrs(&exporter);
            assert_eq!(rendered.len(), 1, "level {level_call} produced no record");
            assert!(
                !rendered[0].contains(SECRET),
                "level {level_call} leaked the secret: {}",
                rendered[0]
            );

            let _ = provider.shutdown();
        }
    }

    #[test]
    fn no_otel_logger_configured_does_not_panic() {
        let layer = SanitizingLayer::new(None);
        let subscriber = tracing_subscriber::registry().with(layer);
        tracing::subscriber::with_default(subscriber, || {
            tracing::info!(password = "irrelevant", "stdout only");
        });
    }
}
