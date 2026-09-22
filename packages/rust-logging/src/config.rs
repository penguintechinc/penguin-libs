//! Environment-derived service configuration -- the only inputs
//! [`crate::telemetry::init`] takes, per `rules/critical-rules.md`
//! Observability ("destination always configurable, never hardcoded").

/// The OTLP wire protocol, mirroring `OTEL_EXPORTER_OTLP_PROTOCOL`'s two
/// documented values.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OtlpProtocol {
    /// `grpc` (the default when unset or unrecognized).
    Grpc,
    /// `http/protobuf`.
    HttpProtobuf,
}

/// Everything [`crate::telemetry::init`] needs, read once from the standard
/// OTLP environment variables plus `LOG_LEVEL`. `OTEL_EXPORTER_OTLP_HEADERS`
/// is deliberately *not* represented here: the OTLP exporters read it
/// directly from the environment (see the `grpc-tonic`/`http-proto`
/// transports' own env handling), so this crate never touches or logs it.
#[derive(Debug, Clone)]
pub struct ServiceConfig {
    /// The service's own name, used as the OTel resource's `service.name`
    /// and as the OTel logger/tracer instrumentation scope name.
    pub service_name: String,
    /// `OTEL_EXPORTER_OTLP_ENDPOINT`. `None` means OTLP export is skipped
    /// entirely -- stdout JSON and the Prometheus `/metrics` surface still
    /// work.
    pub otlp_endpoint: Option<String>,
    /// `OTEL_EXPORTER_OTLP_PROTOCOL`, defaulting to [`OtlpProtocol::Grpc`].
    pub otlp_protocol: OtlpProtocol,
    /// `LOG_LEVEL`, defaulting to `"info"`. Validated by
    /// [`crate::level::LevelHandle`] at init time, not here.
    pub log_level: String,
}

impl ServiceConfig {
    /// Reads the standard OTLP env vars plus `LOG_LEVEL`. `default_service_name`
    /// is used unless `OTEL_SERVICE_NAME` is set, matching every other
    /// PenguinTech service's `ServiceConfig::from_env("svc-process")`-style
    /// call site (see the crate README).
    pub fn from_env(default_service_name: &str) -> Self {
        let service_name = std::env::var("OTEL_SERVICE_NAME")
            .ok()
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| default_service_name.to_string());

        let otlp_endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
            .ok()
            .filter(|value| !value.is_empty());

        let otlp_protocol = match std::env::var("OTEL_EXPORTER_OTLP_PROTOCOL").as_deref() {
            Ok("http/protobuf") => OtlpProtocol::HttpProtobuf,
            _ => OtlpProtocol::Grpc,
        };

        let log_level = std::env::var("LOG_LEVEL")
            .ok()
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "info".to_string());

        Self {
            service_name,
            otlp_endpoint,
            otlp_protocol,
            log_level,
        }
    }
}

#[cfg(test)]
mod tests {
    // This crate denies `unsafe_code` crate-wide (Cargo.toml
    // `[lints.rust]`), but `std::env::set_var`/`remove_var` are `unsafe` as
    // of Rust 2024's stricter signature and these tests are serialized by
    // `ENV_LOCK` below, the documented mitigation for their only hazard
    // (data races with other threads mutating the same process-global
    // environment).
    #![allow(unsafe_code)]
    // `Mutex::lock().unwrap()` on a test-local, never-poisoned lock is the
    // idiomatic pattern (see core/svc_streaming/src/telemetry.rs); denying
    // `unwrap_used` crate-wide is for production code paths, not this.
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::sync::Mutex;

    // std::env is process-global; serialize env-mutating tests so parallel
    // `cargo test` threads don't race on the same variables (same pattern
    // as core/svc_streaming/src/telemetry.rs's ENV_LOCK).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_env() {
        for var in [
            "OTEL_SERVICE_NAME",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "LOG_LEVEL",
        ] {
            // SAFETY: serialized by ENV_LOCK.
            unsafe { std::env::remove_var(var) };
        }
    }

    #[test]
    fn defaults_when_nothing_set() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.service_name, "svc-process");
        assert!(cfg.otlp_endpoint.is_none());
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::Grpc);
        assert_eq!(cfg.log_level, "info");
    }

    #[test]
    fn otel_service_name_overrides_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        // SAFETY: serialized by ENV_LOCK.
        unsafe { std::env::set_var("OTEL_SERVICE_NAME", "svc-process-canary") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.service_name, "svc-process-canary");
        clear_env();
    }

    #[test]
    fn endpoint_and_protocol_and_log_level_are_read() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        // SAFETY: serialized by ENV_LOCK.
        unsafe {
            std::env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317");
            std::env::set_var("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf");
            std::env::set_var("LOG_LEVEL", "debug");
        }
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.otlp_endpoint.as_deref(), Some("http://collector:4317"));
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::HttpProtobuf);
        assert_eq!(cfg.log_level, "debug");
        clear_env();
    }

    #[test]
    fn unrecognized_protocol_falls_back_to_grpc() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        // SAFETY: serialized by ENV_LOCK.
        unsafe { std::env::set_var("OTEL_EXPORTER_OTLP_PROTOCOL", "carrier-pigeon") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::Grpc);
        clear_env();
    }

    #[test]
    fn empty_endpoint_is_treated_as_unset() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        // SAFETY: serialized by ENV_LOCK.
        unsafe { std::env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", "") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert!(cfg.otlp_endpoint.is_none());
        clear_env();
    }
}
