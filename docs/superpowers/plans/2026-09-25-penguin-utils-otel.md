# penguin-utils 0.4.0 — logging + OpenTelemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `init()` call gives a Python service sanitized structured logging plus OTel logs, traces and metrics over an env-configurable OTLP endpoint, with every 0.3.x symbol unchanged.

**Architecture:** structlog output is routed through stdlib `logging` (ProcessorFormatter) so a sanitizing OTel log handler, a console handler and the legacy 0.3.x sinks all hang off the root logger. Traces and metrics use their own OTLP exporters. All redaction flows through one sanitizer driven by a shared test-vector file (reused later by the Rust port). Telemetry lives in a new `telemetry/` subpackage; the OTel-experimental `sdk._logs` import is confined to one file.

**Tech Stack:** Python 3.11+, structlog, opentelemetry-{api,sdk}, opentelemetry-exporter-otlp-proto-{grpc,http}, opentelemetry-instrumentation-{logging,asgi,httpx,sqlalchemy,redis}, pytest, mypy.

**Spec:** `docs/superpowers/specs/2026-09-21-penguin-utils-otel-design.md`

## Global Constraints

- **Package dir:** all paths below are under `packages/python-utils/`. Import name is `penguintechinc_utils`; PyPI name is `penguin-utils`.
- **Version:** target `0.4.0`. `pyproject.toml` `version` is the SINGLE source; `__version__` reads it via `importlib.metadata`; `.version` is regenerated to match (currently stale at `0.2.0.0`).
- **requires-python:** stays `>=3.11` (do NOT raise to 3.13 — library floor ≠ service floor).
- **Dependency specs (required, not extras):** `opentelemetry-api>=1.44.0,<2`, `opentelemetry-sdk>=1.44.0,<2`, `opentelemetry-exporter-otlp-proto-grpc>=1.44.0,<2`, `opentelemetry-exporter-otlp-proto-http>=1.44.0,<2`, `opentelemetry-instrumentation-logging>=0.65b0,<1`, `opentelemetry-instrumentation-asgi>=0.65b0,<1`, `opentelemetry-instrumentation-httpx>=0.65b0,<1`, `opentelemetry-instrumentation-sqlalchemy>=0.65b0,<1`, `opentelemetry-instrumentation-redis>=0.65b0,<1`. Keep `structlog>=23.0`, `httpx>=0.27`, `pydal>=20230521.1` (unused, remove at 1.0).
- **Ranges in the library; exact hashes in CI lock + consumers.** Never exact-pin OTel inside this library's install requires.
- **No hardcoded telemetry destination.** Only `OTEL_*` env vars. Never a vendor URL or SDK.
- **A dead exporter never breaks the app; a sanitizer error never leaks raw data (fail closed).**
- **Coverage gate 90%** (`fail_under=90`); `mypy --strict` on `telemetry/`; every new dataclass is `@dataclass(slots=True)`.
- **TDD:** test first, watch it fail, minimal impl, watch it pass, commit. Commit messages end with the two attribution trailers used on this branch (`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` + `Claude-Session:` line).
- **Deprecated class banned:** never import `opentelemetry.sdk._logs.LoggingHandler` (raises DeprecationWarning in 1.44.0). Use `opentelemetry.instrumentation.logging.handler.LoggingHandler`.

---

### Task 1: Dependencies + single-source version

**Files:**
- Modify: `pyproject.toml` (deps, `[tool.pytest.ini_options]`/`[tool.coverage]`)
- Modify: `src/penguintechinc_utils/__init__.py:7` (`__version__`)
- Modify: `.version`
- Test: `tests/test_version.py`

**Interfaces:**
- Produces: `penguintechinc_utils.__version__: str` (equals installed metadata version).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_version.py
from importlib import metadata
import penguintechinc_utils as u

def test_version_matches_installed_metadata():
    assert u.__version__ == metadata.version("penguin-utils")

def test_version_is_0_4_x():
    assert u.__version__.startswith("0.4.")

def test_otel_imports_are_available():
    import opentelemetry.sdk._logs  # noqa: F401
    from opentelemetry.instrumentation.logging.handler import LoggingHandler  # noqa: F401
    assert LoggingHandler is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/python-utils && pip install -e '.[dev]' && pytest tests/test_version.py -v`
Expected: FAIL — version is `0.3.0`, and OTel not yet a dependency (ImportError).

- [ ] **Step 3: Implement**

In `pyproject.toml` set `version = "0.4.0"`, add the nine OTel deps from Global Constraints to `[project].dependencies`, and add:

```toml
[tool.pytest.ini_options]
addopts = "--cov=penguintechinc_utils --cov-report=term-missing --cov-fail-under=90"

[tool.coverage.run]
branch = true
source = ["penguintechinc_utils"]
```

In `__init__.py` replace the literal with:

```python
from importlib import metadata as _metadata
try:
    __version__ = _metadata.version("penguin-utils")
except _metadata.PackageNotFoundError:  # running from source tree without install
    __version__ = "0.4.0"
```

Set `.version` file contents to `0.4.0.0`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_version.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .version src/penguintechinc_utils/__init__.py tests/test_version.py
git commit -m "chore(python-utils): add OTel deps, single-source version to 0.4.0"
```

---

### Task 2: Sanitizer hardening + shared test vectors

Consolidates redaction into one place, fixes substring over-redaction, redacts emails/tokens anywhere in a string (incl. the message and inside lists), and fails closed. If 0.3.1's `fix/utils-log-redaction` has already merged, the email portion is a no-op — keep the vectors and list/fail-closed additions.

**Files:**
- Modify: `src/penguintechinc_utils/logging.py:21-80` (`SENSITIVE_KEYS`, `EMAIL_REGEX`, `sanitize_log_data`, add `redact_text`, `is_sensitive_key`)
- Create: `tests/vectors/sanitizer_vectors.json`
- Test: `tests/test_sanitizer.py`

**Interfaces:**
- Produces:
  - `sanitize_log_data(data: dict) -> dict` (unchanged signature; now recurses into lists, fails closed)
  - `redact_text(value: str) -> str` (redacts emails/tokens anywhere in a string)
  - `is_sensitive_key(key: str) -> bool` (word/segment match, not raw substring)
  - `SENSITIVE_PLACEHOLDER = "[REDACTED]"`, `SANITIZE_ERROR_PLACEHOLDER = "[REDACTED:sanitize-error]"`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sanitizer.py
import json, pathlib
import pytest
from penguintechinc_utils.logging import (
    sanitize_log_data, redact_text, is_sensitive_key,
    SENSITIVE_PLACEHOLDER, SANITIZE_ERROR_PLACEHOLDER,
)

VECTORS = json.loads((pathlib.Path(__file__).parent / "vectors" / "sanitizer_vectors.json").read_text())

@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_shared_vectors(case):
    assert sanitize_log_data(case["input"]) == case["expected"]

def test_key_match_is_not_naive_substring():
    # "footprint" contains "otp" but must NOT be treated as sensitive
    assert is_sensitive_key("footprint") is False
    assert is_sensitive_key("otp") is True
    assert is_sensitive_key("mfa_code") is True

def test_email_redacted_mid_string():
    assert "alice@example.com" not in redact_text("user alice@example.com logged in")

def test_list_values_are_scanned():
    out = sanitize_log_data({"items": ["ok", "bob@example.com"]})
    assert "bob@example.com" not in json.dumps(out)

def test_fail_closed_on_hostile_repr():
    class Boom:
        def __repr__(self): raise RuntimeError("nope")
    out = sanitize_log_data({"x": Boom()})
    assert out["x"] == SANITIZE_ERROR_PLACEHOLDER
```

Create `tests/vectors/sanitizer_vectors.json` (this file is the cross-language contract — the Rust port reuses it verbatim):

```json
[
  {"name": "password_key", "input": {"password": "hunter2"}, "expected": {"password": "[REDACTED]"}},
  {"name": "token_key", "input": {"api_key": "sk-abc"}, "expected": {"api_key": "[REDACTED]"}},
  {"name": "non_sensitive_substring", "input": {"footprint": "boot"}, "expected": {"footprint": "boot"}},
  {"name": "email_in_message", "input": {"event": "login for carol@ex.com"}, "expected": {"event": "login for [email]"}},
  {"name": "nested_dict", "input": {"outer": {"secret": "s"}}, "expected": {"outer": {"secret": "[REDACTED]"}}},
  {"name": "list_of_strings", "input": {"xs": ["dan@ex.com", "ok"]}, "expected": {"xs": ["[email]", "ok"]}}
]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sanitizer.py -v`
Expected: FAIL — `redact_text`/`is_sensitive_key` don't exist; substring match over-redacts; lists not scanned.

- [ ] **Step 3: Implement** in `logging.py`

```python
SENSITIVE_PLACEHOLDER = "[REDACTED]"
SANITIZE_ERROR_PLACEHOLDER = "[REDACTED:sanitize-error]"
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_KEY_SPLIT = re.compile(r"[^a-z0-9]+")

def is_sensitive_key(key: str) -> bool:
    """True if a key names a secret. Matches on word segments, not raw substrings."""
    segments = set(_KEY_SPLIT.split(key.lower()))
    return bool(segments & SENSITIVE_KEYS)

def redact_text(value: str) -> str:
    """Redact emails (and add token patterns here) anywhere within a string."""
    return EMAIL_REGEX.sub("[email]", value)

def _sanitize_value(value):
    if isinstance(value, dict):
        return sanitize_log_data(value)
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value

def sanitize_log_data(data: dict) -> dict:
    """Return a copy with sensitive keys redacted and PII patterns scrubbed. Fails closed."""
    out = {}
    for key, value in data.items():
        try:
            out[key] = SENSITIVE_PLACEHOLDER if is_sensitive_key(key) else _sanitize_value(value)
        except Exception:
            out[key] = SANITIZE_ERROR_PLACEHOLDER
    return out
```

Ensure `SENSITIVE_KEYS` is a `frozenset` of the existing bare tokens (password, passwd, secret, token, api_key, apikey, auth_token, authtoken, access_token, refresh_token, credential, credentials, mfa_code, totp_code, otp, captcha_token, session_id, sessionid, cookie, authorization).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sanitizer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/logging.py tests/test_sanitizer.py tests/vectors/sanitizer_vectors.json
git commit -m "fix(python-utils): word-boundary key match, mid-string + list redaction, fail-closed; shared vectors"
```

---

### Task 3: TelemetryConfig (env/arg resolution)

**Files:**
- Create: `src/penguintechinc_utils/telemetry/__init__.py` (empty for now)
- Create: `src/penguintechinc_utils/telemetry/config.py`
- Test: `tests/test_telemetry_config.py`

**Interfaces:**
- Produces: `TelemetryConfig` `@dataclass(slots=True)` with fields `service_name: str`, `service_version: str | None`, `level: int`, `log_format: str` (`"json"|"console"`), `otlp_endpoint: str | None`, `sdk_disabled: bool`; classmethod `resolve(*, service_name=None, service_version=None, level=None, log_format=None) -> TelemetryConfig` applying arg > env > default. Raises `ValueError`/`TypeError` on bad ARGS; WARNs and falls back on bad ENV.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telemetry_config.py
import logging, pytest
from penguintechinc_utils.telemetry.config import TelemetryConfig

def test_arg_beats_env(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    cfg = TelemetryConfig.resolve(service_name="from-arg")
    assert cfg.service_name == "from-arg"

def test_env_level_parsed(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert TelemetryConfig.resolve(service_name="s").level == logging.DEBUG

def test_bad_env_level_warns_and_defaults(monkeypatch, caplog):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve(service_name="s")
    assert cfg.level == logging.INFO
    assert any("LOG_LEVEL" in r.message for r in caplog.records)

def test_bad_arg_level_raises():
    with pytest.raises((ValueError, TypeError)):
        TelemetryConfig.resolve(service_name="s", level="verbose")

def test_missing_service_name_warns_and_falls_back(monkeypatch, caplog):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    with caplog.at_level(logging.WARNING):
        cfg = TelemetryConfig.resolve()
    assert cfg.service_name.startswith("unknown_service")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_telemetry_config.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `telemetry/config.py`

```python
"""Resolve telemetry configuration from explicit args, then env, then defaults."""
from __future__ import annotations
import logging, os, sys
from dataclasses import dataclass

_LOG = logging.getLogger(__name__)

def _resolve_level(level, env_val) -> int:
    if level is not None:
        if isinstance(level, int):
            return level
        parsed = logging.getLevelName(str(level).upper())
        if not isinstance(parsed, int):
            raise ValueError(f"invalid level argument: {level!r}")
        return parsed
    if env_val:
        parsed = logging.getLevelName(env_val.upper())
        if isinstance(parsed, int):
            return parsed
        _LOG.warning("ignoring invalid LOG_LEVEL=%r; defaulting to INFO", env_val)
    return logging.INFO

@dataclass(slots=True)
class TelemetryConfig:
    service_name: str
    service_version: str | None
    level: int
    log_format: str
    otlp_endpoint: str | None
    sdk_disabled: bool

    @classmethod
    def resolve(cls, *, service_name=None, service_version=None, level=None, log_format=None) -> "TelemetryConfig":
        name = service_name or os.getenv("OTEL_SERVICE_NAME")
        if not name:
            name = f"unknown_service:{os.path.basename(sys.argv[0]) or 'python'}"
            _LOG.warning("no service_name/OTEL_SERVICE_NAME set; using %r", name)
        fmt = log_format or os.getenv("LOG_FORMAT") or ("console" if sys.stdout.isatty() else "json")
        if fmt not in ("json", "console"):
            if log_format is not None:
                raise ValueError(f"invalid log_format argument: {log_format!r}")
            _LOG.warning("ignoring invalid LOG_FORMAT=%r; defaulting to json", fmt)
            fmt = "json"
        return cls(
            service_name=name,
            service_version=service_version,
            level=_resolve_level(level, os.getenv("LOG_LEVEL")),
            log_format=fmt,
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            sdk_disabled=os.getenv("OTEL_SDK_DISABLED", "").lower() == "true",
        )
```

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_telemetry_config.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/__init__.py src/penguintechinc_utils/telemetry/config.py tests/test_telemetry_config.py
git commit -m "feat(python-utils): TelemetryConfig arg>env>default resolution"
```

---

### Task 4: Providers (resource + exporters, graceful no-endpoint)

**Files:**
- Create: `src/penguintechinc_utils/telemetry/providers.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `TelemetryConfig` (Task 3).
- Produces: `build_providers(cfg: TelemetryConfig) -> Providers` where `Providers` is `@dataclass(slots=True)` with `tracer_provider`, `meter_provider`, `logger_provider`, `exporting: bool`. When `cfg.otlp_endpoint` is falsy or `cfg.sdk_disabled`, providers are still built (in-process) but no OTLP exporter/processor is attached and `exporting=False` with one WARN. Protocol selection reads `OTEL_EXPORTER_OTLP_PROTOCOL` (`grpc` default, else `http/protobuf`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_providers.py
import logging
from penguintechinc_utils.telemetry.config import TelemetryConfig
from penguintechinc_utils.telemetry.providers import build_providers

def _cfg(**kw):
    base = dict(service_name="svc", service_version=None, level=logging.INFO,
                log_format="json", otlp_endpoint=None, sdk_disabled=False)
    base.update(kw); return TelemetryConfig(**base)

def test_no_endpoint_builds_inprocess_no_export(caplog):
    with caplog.at_level(logging.WARNING):
        p = build_providers(_cfg(otlp_endpoint=None))
    assert p.exporting is False
    assert p.tracer_provider is not None and p.meter_provider is not None and p.logger_provider is not None

def test_endpoint_enables_export():
    p = build_providers(_cfg(otlp_endpoint="http://localhost:4317"))
    assert p.exporting is True

def test_resource_has_service_name():
    p = build_providers(_cfg(service_name="svc"))
    attrs = p.tracer_provider.resource.attributes
    assert attrs["service.name"] == "svc"
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `telemetry/providers.py`

```python
"""Construct OTel Tracer/Meter/Logger providers and (optionally) OTLP exporters."""
from __future__ import annotations
import logging, os
from dataclasses import dataclass
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from .config import TelemetryConfig

_LOG = logging.getLogger(__name__)

@dataclass(slots=True)
class Providers:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    exporting: bool

def _http() -> bool:
    return os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").startswith("http")

def _exporters():
    if _http():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    return OTLPSpanExporter(), OTLPMetricExporter(), OTLPLogExporter()

def build_providers(cfg: TelemetryConfig, span_processor_factory=BatchSpanProcessor) -> Providers:
    res_attrs = {"service.name": cfg.service_name}
    if cfg.service_version:
        res_attrs["service.version"] = cfg.service_version
    resource = Resource.create(res_attrs)
    exporting = bool(cfg.otlp_endpoint) and not cfg.sdk_disabled
    if not exporting:
        _LOG.warning("OTLP endpoint unset or SDK disabled; telemetry stays in-process (not exported)")
        tp = TracerProvider(resource=resource)
        mp = MeterProvider(resource=resource)
        lp = LoggerProvider(resource=resource)
        return Providers(tp, mp, lp, exporting=False)
    span_exp, metric_exp, log_exp = _exporters()
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(span_processor_factory(span_exp))
    mp = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(metric_exp)])
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(log_exp))
    return Providers(tp, mp, lp, exporting=True)
```

> Executor note: the span exporter is passed through `span_processor_factory` so Task 5 can wrap it with sanitization without editing this file.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/providers.py tests/test_providers.py
git commit -m "feat(python-utils): OTel providers with graceful no-endpoint path"
```

---

### Task 5: Bridge (sanitizing log handler + span sanitization)

**Files:**
- Create: `src/penguintechinc_utils/telemetry/bridge.py`
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `sanitize_log_data`, `redact_text` (Task 2); `LoggerProvider` (Task 4).
- Produces:
  - `SanitizingLogHandler(logger_provider)` — subclass of `opentelemetry.instrumentation.logging.handler.LoggingHandler`; sanitizes `record.msg`, `record.args`, and any dict in `record.__dict__` extras before emit.
  - `SanitizingSpanProcessorFactory(inner_exporter) -> BatchSpanProcessor` — returns a batch processor whose exporter first redacts span attribute values and event attributes. Signature matches `span_processor_factory` in Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bridge.py
import logging
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from penguintechinc_utils.telemetry.bridge import SanitizingLogHandler

def test_handler_redacts_email_in_message():
    lp = LoggerProvider()
    exp = InMemoryLogExporter()
    lp.add_log_record_processor(SimpleLogRecordProcessor(exp))
    handler = SanitizingLogHandler(logger_provider=lp)
    logger = logging.getLogger("t.bridge"); logger.addHandler(handler); logger.setLevel(logging.INFO)
    logger.info("login for eve@example.com")
    lp.force_flush()
    bodies = [r.log_record.body for r in exp.get_finished_logs()]
    assert bodies and all("eve@example.com" not in str(b) for b in bodies)

def test_handler_is_not_deprecated_sdk_class():
    import opentelemetry.instrumentation.logging.handler as h
    assert issubclass(SanitizingLogHandler, h.LoggingHandler)
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module missing).

- [ ] **Step 3: Implement** `telemetry/bridge.py`

```python
"""Bridge stdlib log records and spans into OTel, sanitizing before export."""
from __future__ import annotations
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from ..logging import redact_text, is_sensitive_key

class SanitizingLogHandler(LoggingHandler):
    """LoggingHandler that scrubs PII/secrets from a record before it becomes an OTel LogRecord."""
    def emit(self, record):
        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            if record.args:
                record.args = tuple(redact_text(a) if isinstance(a, str) else a for a in record.args)
        except Exception:
            record.msg = "[REDACTED:sanitize-error]"; record.args = ()
        super().emit(record)

class _SanitizingSpanExporter(SpanExporter):
    """Wrap a span exporter, redacting attribute + event values before delegating."""
    def __init__(self, inner: SpanExporter):
        self._inner = inner
    def export(self, spans):
        for span in spans:
            attrs = dict(span.attributes or {})
            for k, v in list(attrs.items()):
                attrs[k] = "[REDACTED]" if is_sensitive_key(k) else (redact_text(v) if isinstance(v, str) else v)
            span._attributes = attrs  # BoundedAttributes replacement; executor: verify attr name on the pinned SDK
        return self._inner.export(spans)
    def shutdown(self): return self._inner.shutdown()
    def force_flush(self, timeout_millis: int = 30000): return self._inner.force_flush(timeout_millis)

def SanitizingSpanProcessorFactory(inner_exporter: SpanExporter) -> BatchSpanProcessor:
    return BatchSpanProcessor(_SanitizingSpanExporter(inner_exporter))
```

> Executor note: confirm the ReadableSpan attribute backing field on opentelemetry-sdk 1.44.0 (`_attributes`). If it differs, adapt; the test in Task 13 (redaction proof) is the real gate.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/bridge.py tests/test_bridge.py
git commit -m "feat(python-utils): sanitizing OTel log handler + span exporter wrapper"
```

---

### Task 6: Trace-context structlog processor

**Files:**
- Create: `src/penguintechinc_utils/telemetry/context.py`
- Test: `tests/test_context_processor.py`

**Interfaces:**
- Produces: `add_trace_context(logger, method_name, event_dict) -> dict` — a structlog processor injecting `trace_id`/`span_id` (32/16 hex) when a span is recording; a no-op otherwise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context_processor.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from penguintechinc_utils.telemetry.context import add_trace_context

def test_injects_ids_inside_span():
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("t")
    with tracer.start_as_current_span("s"):
        out = add_trace_context(None, "info", {"event": "x"})
    assert len(out["trace_id"]) == 32 and len(out["span_id"]) == 16

def test_noop_without_span():
    out = add_trace_context(None, "info", {"event": "x"})
    assert "trace_id" not in out
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement** `telemetry/context.py`

```python
"""structlog processor that stamps the active OTel trace/span id onto each event."""
from __future__ import annotations
from opentelemetry import trace

def add_trace_context(logger, method_name, event_dict):
    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if ctx and ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
```

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/context.py tests/test_context_processor.py
git commit -m "feat(python-utils): structlog trace-context processor"
```

---

### Task 7: Rewire logging.py onto stdlib (public API unchanged)

**Files:**
- Modify: `src/penguintechinc_utils/logging.py` (`configure_logging`, `get_logger`)
- Test: `tests/test_logging_stdlib.py`

**Interfaces:**
- Consumes: `add_trace_context` (Task 6).
- Produces (unchanged signatures): `configure_logging(level=logging.INFO, json_output=False, sinks=None)`, `get_logger(name=None, level=None)`. structlog now uses `stdlib.LoggerFactory` + `ProcessorFormatter`; `level` is enforced on the stdlib logger; `get_logger` still returns a structlog `BoundLogger`. `configure_logging` stays logs-only (no OTel).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logging_stdlib.py
import logging, structlog
from penguintechinc_utils.logging import configure_logging, get_logger

def test_get_logger_returns_bound_logger():
    configure_logging(level=logging.INFO, json_output=True)
    assert isinstance(get_logger("x"), structlog.stdlib.BoundLogger)

def test_level_is_enforced(caplog):
    configure_logging(level=logging.INFO)
    log = get_logger("lvl")
    with caplog.at_level(logging.DEBUG, logger="lvl"):
        log.debug("should_be_filtered")
    assert not any("should_be_filtered" in r.message for r in caplog.records if r.levelno == logging.DEBUG and r.name == "lvl")

def test_records_reach_stdlib_root():
    configure_logging(level=logging.INFO, json_output=True)
    root = logging.getLogger()
    assert root.handlers, "configure_logging must attach a stdlib handler"
```

- [ ] **Step 2: Run to verify it fails** — FAIL (currently PrintLoggerFactory; no stdlib handler; DEBUG prints).

- [ ] **Step 3: Implement** — replace the `structlog.configure(...)` block and `configure_logging`/`get_logger` bodies:

```python
import structlog
from structlog.stdlib import LoggerFactory, BoundLogger, ProcessorFormatter, add_log_level, add_logger_name
from .telemetry.context import add_trace_context

_SHARED_PROCESSORS = [
    add_log_level, add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    add_trace_context,
    lambda logger, name, ed: sanitize_log_data(ed),
]

def configure_logging(level=logging.INFO, json_output=False, sinks=None):
    """Configure structlog to render through stdlib logging. Logs only; call init() for OTel."""
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer(colors=False)
    formatter = ProcessorFormatter(processor=renderer, foreign_pre_chain=_SHARED_PROCESSORS)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    if sinks:
        root.addHandler(_LegacySinkHandler(sinks, renderer))  # defined in Task 8
    root.setLevel(level)
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, ProcessorFormatter.wrap_for_formatter],
        logger_factory=LoggerFactory(),
        wrapper_class=BoundLogger,
        cache_logger_on_first_use=True,
    )

def get_logger(name=None, level=None):
    """Return a structlog BoundLogger routed through stdlib logging."""
    if level is not None:
        logging.getLogger(name).setLevel(level)
    return structlog.get_logger(name)
```

If Task 8 is not yet implemented, temporarily guard the `sinks` branch (`if sinks:` → `pass`) and restore in Task 8; note this in the commit.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/logging.py tests/test_logging_stdlib.py
git commit -m "refactor(python-utils): route structlog through stdlib; enforce level"
```

---

### Task 8: Fault-isolated + async sink dispatch

**Files:**
- Modify: `src/penguintechinc_utils/logging.py` (add `_LegacySinkHandler`)
- Modify: `src/penguintechinc_utils/sinks.py` (add `AsyncSink` wrapper)
- Test: `tests/test_sink_isolation.py`

**Interfaces:**
- Produces:
  - `_LegacySinkHandler(sinks: list[Sink], renderer)` — a `logging.Handler` that renders the record to a dict and calls each sink's `emit`, catching per-sink exceptions (counted, never raised) so one failing sink never affects the log call or the other sinks.
  - `AsyncSink(inner: Sink, maxsize=10000)` — wraps a blocking network sink with a bounded queue + daemon worker thread; drops oldest on overflow; `flush()`/`close()` drain. Stdout/File/Callback are NOT wrapped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sink_isolation.py
import logging
from penguintechinc_utils.logging import configure_logging, get_logger
from penguintechinc_utils.sinks import CallbackSink, AsyncSink

def test_one_failing_sink_does_not_break_logging():
    seen = []
    good = CallbackSink(lambda e: seen.append(e))
    class Bad:
        def emit(self, e): raise RuntimeError("boom")
        def flush(self): pass
        def close(self): pass
    configure_logging(level=logging.INFO, json_output=True, sinks=[Bad(), good])
    get_logger("iso").info("hello")
    assert seen, "healthy sink must still receive the event"

def test_async_sink_drains_on_close():
    got = []
    inner = CallbackSink(lambda e: got.append(e))
    a = AsyncSink(inner)
    a.emit({"event": "x"}); a.close()
    assert got == [{"event": "x"}]
```

- [ ] **Step 2: Run to verify it fails** — FAIL (`AsyncSink`/`_LegacySinkHandler` missing).

- [ ] **Step 3: Implement**

`sinks.py` — add:

```python
import queue, threading
class AsyncSink:
    """Wrap a blocking sink with a bounded background queue; drop oldest on overflow."""
    _SENTINEL = object()
    def __init__(self, inner, maxsize: int = 10000):
        self._inner = inner
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._dropped = 0
        self._t = threading.Thread(target=self._run, daemon=True); self._t.start()
    def emit(self, event: dict) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            try: self._q.get_nowait()
            except queue.Empty: pass
            self._dropped += 1
            try: self._q.put_nowait(event)
            except queue.Full: pass
    def _run(self):
        while True:
            item = self._q.get()
            if item is self._SENTINEL: return
            try: self._inner.emit(item)
            except Exception: pass
            finally: self._q.task_done()
    def flush(self) -> None:
        self._q.join(); self._inner.flush()
    def close(self) -> None:
        self._q.join(); self._q.put(self._SENTINEL); self._t.join(timeout=5); self._inner.close()
```

`logging.py` — add the handler and restore the `sinks` branch from Task 7:

```python
class _LegacySinkHandler(logging.Handler):
    """Fan a rendered record out to 0.3.x sinks, isolating per-sink failures."""
    def __init__(self, sinks, renderer):
        super().__init__()
        self._sinks = sinks
        self._errors = 0
    def emit(self, record):
        event = getattr(record, "msg", None)
        payload = event if isinstance(event, dict) else {"event": record.getMessage()}
        for sink in self._sinks:
            try:
                sink.emit(sanitize_log_data(dict(payload)))
            except Exception:
                self._errors += 1
```

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/sinks.py src/penguintechinc_utils/logging.py tests/test_sink_isolation.py
git commit -m "feat(python-utils): fault-isolated sink fan-out + AsyncSink queue"
```

---

### Task 9: KillKrill flush off the caller thread

**Files:**
- Modify: `src/penguintechinc_utils/killkrill.py` (`emit`, `_flush`)
- Test: `tests/test_killkrill_nonblocking.py`

**Interfaces:**
- Produces: `KillKrillSink.emit` never performs network I/O on the caller thread. When the buffer is full it signals the background flush thread (Event/condition) rather than calling `_flush()` inline. Existing `KillKrillConfig`/constructor unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_killkrill_nonblocking.py
import time
from penguintechinc_utils.killkrill import KillKrillSink, KillKrillConfig

def test_emit_returns_immediately_when_batch_full(monkeypatch):
    sink = KillKrillSink(KillKrillConfig(endpoint="http://localhost:1", batch_size=1))
    def slow_flush(*a, **k): time.sleep(2)
    monkeypatch.setattr(sink, "_flush", slow_flush)
    start = time.monotonic()
    sink.emit({"event": "a"}); sink.emit({"event": "b"})
    assert time.monotonic() - start < 0.5, "emit must not block on flush"
    sink.close()
```

- [ ] **Step 2: Run to verify it fails** — FAIL (current `emit` calls `_flush()` inline at `killkrill.py:94`).

- [ ] **Step 3: Implement** — replace the inline-flush branch in `emit` with a signal to the existing flush thread:

```python
def emit(self, event):
    with self._lock:
        self._buffer.events.append(event)
        full = len(self._buffer.events) >= self._config.batch_size
    if full:
        self._flush_now.set()   # threading.Event created in __init__; _flush_loop waits on it with timeout
```

In `_flush_loop`, wait on `self._flush_now.wait(timeout=5)` then clear it and flush; keep the 5s periodic flush as the timeout branch.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/killkrill.py tests/test_killkrill_nonblocking.py
git commit -m "fix(python-utils): KillKrill flush on background thread, never the caller"
```

---

### Task 10: Instrumentation (ASGI + conditional httpx/sqlalchemy/redis)

**Files:**
- Create: `src/penguintechinc_utils/telemetry/instrument.py`
- Test: `tests/test_instrument.py`

**Interfaces:**
- Consumes: `TracerProvider`, `MeterProvider` (Task 4).
- Produces: `instrument(app=None, *, tracer_provider, meter_provider) -> None` — wraps an ASGI/Quart app when given; calls each of `HTTPXClientInstrumentor`, `SQLAlchemyInstrumentor`, `RedisInstrumentor` only if importable; each failure/absence is a DEBUG log, never a raise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_instrument.py
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from penguintechinc_utils.telemetry.instrument import instrument

def test_instrument_without_app_is_safe():
    instrument(app=None, tracer_provider=TracerProvider(), meter_provider=MeterProvider())

def test_instrument_wraps_asgi_app():
    calls = {}
    async def app(scope, receive, send): calls["hit"] = True
    wrapped = instrument(app=app, tracer_provider=TracerProvider(), meter_provider=MeterProvider())
    assert wrapped is not None
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement** `telemetry/instrument.py`

```python
"""Optional auto-instrumentation. Every hook is best-effort; absence is never fatal."""
from __future__ import annotations
import logging
_LOG = logging.getLogger(__name__)

def instrument(app=None, *, tracer_provider, meter_provider):
    wrapped = None
    if app is not None:
        try:
            from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
            wrapped = OpenTelemetryMiddleware(app, tracer_provider=tracer_provider, meter_provider=meter_provider)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.debug("ASGI instrumentation unavailable: %s", exc)
    for mod, cls in (("httpx", "HTTPXClientInstrumentor"),
                     ("sqlalchemy", "SQLAlchemyInstrumentor"),
                     ("redis", "RedisInstrumentor")):
        try:
            pkg = __import__(f"opentelemetry.instrumentation.{mod}", fromlist=[cls])
            getattr(pkg, cls)().instrument(tracer_provider=tracer_provider)
        except Exception as exc:
            _LOG.debug("%s instrumentation skipped: %s", mod, exc)
    return wrapped
```

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/instrument.py tests/test_instrument.py
git commit -m "feat(python-utils): optional ASGI/httpx/sqlalchemy/redis instrumentation"
```

---

### Task 11: Helpers (get_tracer, get_meter, timed)

**Files:**
- Create: `src/penguintechinc_utils/telemetry/helpers.py`
- Test: `tests/test_helpers.py`

**Interfaces:**
- Produces: `get_tracer(name)`, `get_meter(name)`, `timed(name, meter=None, tracer=None)` — usable as a decorator or context manager; records a span plus a duration histogram `<name>.duration` (milliseconds).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_helpers.py
from penguintechinc_utils.telemetry.helpers import timed, get_tracer, get_meter

def test_timed_context_manager_runs_body():
    ran = {}
    with timed("op.test"):
        ran["yes"] = True
    assert ran["yes"]

def test_timed_decorator_returns_value():
    @timed("op.dec")
    def add(a, b): return a + b
    assert add(2, 3) == 5

def test_get_tracer_and_meter():
    assert get_tracer("t") is not None and get_meter("m") is not None
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement** `telemetry/helpers.py`

```python
"""Thin helpers over the OTel API plus a span+histogram timing decorator/CM."""
from __future__ import annotations
import functools, time
from contextlib import ContextDecorator
from opentelemetry import trace, metrics

def get_tracer(name: str): return trace.get_tracer(name)
def get_meter(name: str): return metrics.get_meter(name)

class timed(ContextDecorator):
    """Record a span and a `<name>.duration` millisecond histogram around a block or function."""
    def __init__(self, name: str, meter=None, tracer=None):
        self._name = name
        self._hist = (meter or get_meter("penguin_utils")).create_histogram(
            f"{name}.duration", unit="ms", description=f"duration of {name}")
        self._tracer = tracer or get_tracer("penguin_utils")
    def __enter__(self):
        self._span_cm = self._tracer.start_as_current_span(self._name)
        self._span_cm.__enter__(); self._start = time.perf_counter(); return self
    def __exit__(self, *exc):
        self._hist.record((time.perf_counter() - self._start) * 1000.0)
        return self._span_cm.__exit__(*exc)
```

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/helpers.py tests/test_helpers.py
git commit -m "feat(python-utils): get_tracer/get_meter/timed helpers"
```

---

### Task 12: init() + Telemetry handle + exports + API contract

**Files:**
- Modify: `src/penguintechinc_utils/telemetry/__init__.py` (`init`, `Telemetry`)
- Modify: `src/penguintechinc_utils/__init__.py` (`__all__`, new exports)
- Test: `tests/test_init.py`, `tests/test_api_contract.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `init(*, service_name=None, service_version=None, level=None, log_format=None, app=None, sinks=None) -> Telemetry`
  - `Telemetry` `@dataclass(slots=True)`: `.providers`, `.app` (wrapped ASGI app or None), `.shutdown()`.
  - Re-exported at top level: `init`, `get_logger`, `get_tracer`, `get_meter`, `timed`, plus all 0.3.x names.
  - Idempotent: second `init()` returns the same handle + WARN; duplicate OTel handler on root logger is not added twice.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_init.py
import logging
import penguintechinc_utils as u

def test_init_returns_handle_and_configures_logging(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    tel = u.init(service_name="svc")
    assert tel.providers.exporting is False
    assert logging.getLogger().handlers
    tel.shutdown()

def test_init_is_idempotent(monkeypatch, caplog):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    a = u.init(service_name="svc")
    with caplog.at_level(logging.WARNING):
        b = u.init(service_name="svc")
    assert a is b
    otel_handlers = [h for h in logging.getLogger().handlers if h.__class__.__name__ == "SanitizingLogHandler"]
    assert len(otel_handlers) <= 1
    a.shutdown()

def test_init_in_forked_worker_is_safe(monkeypatch):
    # Pre-fork servers (hypercorn/gunicorn) call init() in each worker; the batch
    # processors must reinitialise after fork rather than deadlock. Skips on platforms without fork.
    import os, sys
    if not hasattr(os, "fork") or sys.platform == "win32":
        import pytest; pytest.skip("no os.fork")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    pid = os.fork()
    if pid == 0:  # child
        try:
            import penguintechinc_utils as u2
            u2.init(service_name="child"); u2.get_logger("c").info("in-child")
            os._exit(0)
        except Exception:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
```

```python
# tests/test_api_contract.py
import inspect
import penguintechinc_utils as u

def test_03x_symbols_present():
    for name in ("configure_logging", "configure_logging_from_env", "get_logger",
                 "sanitize_log_data", "SanitizedLogger", "Sink", "StdoutSink",
                 "KillKrillSink", "KillKrillConfig"):
        assert hasattr(u, name), name

def test_configure_logging_signature_unchanged():
    params = list(inspect.signature(u.configure_logging).parameters)
    assert params == ["level", "json_output", "sinks"]

def test_new_symbols_present():
    for name in ("init", "get_tracer", "get_meter", "timed"):
        assert hasattr(u, name), name
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement** `telemetry/__init__.py`

```python
"""One-call logging + OTel setup for penguin-utils."""
from __future__ import annotations
import atexit, logging
from dataclasses import dataclass
from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from ..logging import configure_logging
from .config import TelemetryConfig
from .providers import build_providers, Providers
from .bridge import SanitizingLogHandler, SanitizingSpanProcessorFactory
from .instrument import instrument

_LOG = logging.getLogger(__name__)
_STATE: "Telemetry | None" = None

@dataclass(slots=True)
class Telemetry:
    providers: Providers
    app: object | None
    _shutdown_done: bool = False
    def shutdown(self):
        if self._shutdown_done: return
        self._shutdown_done = True
        for p in (self.providers.tracer_provider, self.providers.meter_provider, self.providers.logger_provider):
            try: p.shutdown()
            except Exception: pass

def init(*, service_name=None, service_version=None, level=None, log_format=None, app=None, sinks=None) -> Telemetry:
    global _STATE
    if _STATE is not None:
        _LOG.warning("penguin-utils init() already called; returning existing handle")
        return _STATE
    cfg = TelemetryConfig.resolve(service_name=service_name, service_version=service_version,
                                  level=level, log_format=log_format)
    providers = build_providers(cfg, span_processor_factory=SanitizingSpanProcessorFactory)
    trace.set_tracer_provider(providers.tracer_provider)
    metrics.set_meter_provider(providers.meter_provider)
    set_logger_provider(providers.logger_provider)
    configure_logging(level=cfg.level, json_output=(cfg.log_format == "json"), sinks=sinks)
    root = logging.getLogger()
    if not any(isinstance(h, SanitizingLogHandler) for h in root.handlers):
        handler = SanitizingLogHandler(logger_provider=providers.logger_provider)
        handler.setLevel(cfg.level); root.addHandler(handler)
    for noisy in ("opentelemetry", "grpc"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    wrapped = instrument(app=app, tracer_provider=providers.tracer_provider,
                         meter_provider=providers.meter_provider)
    _STATE = Telemetry(providers=providers, app=wrapped or app)
    atexit.register(_STATE.shutdown)
    return _STATE
```

Add to top-level `__init__.py`:

```python
from .telemetry import init, Telemetry
from .telemetry.helpers import get_tracer, get_meter, timed
```
and extend `__all__` with `"init", "Telemetry", "get_tracer", "get_meter", "timed"`.

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_init.py tests/test_api_contract.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/penguintechinc_utils/telemetry/__init__.py src/penguintechinc_utils/__init__.py tests/test_init.py tests/test_api_contract.py
git commit -m "feat(python-utils): init() one-call logging + OTel; export new API"
```

---

### Task 13: Integration test against a real collector + redaction proof

**Files:**
- Create: `tests/integration/test_otlp_export.py`
- Create: `tests/integration/collector-config.yaml`
- Create: `tests/integration/conftest.py` (collector fixture)
- Modify: `pyproject.toml` (`[tool.pytest]` markers: `integration`)

**Interfaces:**
- Consumes: `init` (Task 12), `timed` (Task 11).
- Produces: a test asserting exported `logRecords>=1`, `metrics>=1`, histogram metrics `>=1`, `spans>=1`, printing each count; and a redaction-proof test asserting a planted email/token appears **0** times in the exported JSON while a planted non-sensitive marker appears `>=1` time.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_otlp_export.py
import json, os, time, pytest
pytestmark = pytest.mark.integration

def _counts(path):
    logs = metrics = hist = spans = 0
    for line in open(path):
        line = line.strip()
        if not line: continue
        d = json.loads(line)
        for rl in d.get("resourceLogs", []):
            for sl in rl.get("scopeLogs", []): logs += len(sl.get("logRecords", []))
        for rm in d.get("resourceMetrics", []):
            for sm in rm.get("scopeMetrics", []):
                for m in sm.get("metrics", []):
                    metrics += 1
                    if "histogram" in m or "exponentialHistogram" in m: hist += 1
        for rs in d.get("resourceTraces", []):
            for ss in rs.get("scopeSpans", []): spans += len(ss.get("spans", []))
    return logs, metrics, hist, spans

def test_all_signals_and_redaction(otlp_collector):
    import penguintechinc_utils as u
    tel = u.init(service_name="itest")
    log = u.get_logger("itest")
    log.info("marker_ok user planted_secret@example.com token=sk-PLANTED")
    with u.timed("itest.work"):
        time.sleep(0.01)
    tel.shutdown(); time.sleep(2)
    out = otlp_collector["output"]
    logs, metrics, hist, spans = _counts(out)
    print(f"logRecords={logs} metrics={metrics} histograms={hist} spans={spans}")
    assert logs >= 1 and metrics >= 1 and hist >= 1 and spans >= 1
    blob = open(out).read()
    assert "planted_secret@example.com" not in blob and "sk-PLANTED" not in blob
    assert "marker_ok" in blob  # proves export actually happened (non-zero denominator)
```

`conftest.py`: a fixture starting `otel/opentelemetry-collector-contrib:0.144.0` (pinned by digest in CI) with the file exporter writing to a temp path, exposing `{"output": <path>}`, and setting `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_METRIC_EXPORT_INTERVAL=500`. `collector-config.yaml`: OTLP receiver on 4317/4318 → file exporter (mirror the `testing-app` skill's collector setup).

- [ ] **Step 2: Run to verify it fails** — FAIL (no collector fixture / assertions unmet).

- [ ] **Step 3: Implement** the fixture + config. Set `[tool.pytest.ini_options] markers = ["integration: needs a running OTLP collector"]`. Keep integration tests out of the default coverage run (`-m "not integration"` in the unit target).

- [ ] **Step 4: Run to verify it passes** — `pytest tests/integration -m integration -v -s` → PASS, counts printed non-zero.

- [ ] **Step 5: Commit**

```bash
git add tests/integration pyproject.toml
git commit -m "test(python-utils): OTLP integration + redaction proof against real collector"
```

---

### Task 14: Consumer compat + CI job + coverage/mypy gates + Makefile

**Files:**
- Create: `tests/test_consumer_compat.py`
- Modify: `.github/workflows/ci.yml` (add a `python-utils` test job on 3.11/3.12/3.13)
- Modify: `Makefile` (ensure `test` runs with coverage; add mypy for `telemetry/`)

**Interfaces:**
- Produces: proof the built wheel installs clean and the real 0.3.x usage from consumers still imports/runs; CI actually executes the suite (a job that can fail).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_consumer_compat.py
# Mirrors the exact 0.3.x call sites in gough / license-server / penguincloud / elder.
from penguintechinc_utils import get_logger, SanitizedLogger, sanitize_log_data
from penguintechinc_utils.logging import configure_logging_from_env

def test_get_logger_call_site():
    assert get_logger("svc") is not None

def test_sanitized_logger_call_site():
    logs = []
    SanitizedLogger("app", sinks=[]).info("x", {"password": "p"})  # must not raise

def test_configure_logging_from_env_returns_sinks(monkeypatch):
    monkeypatch.delenv("LOG_KAFKA_SERVERS", raising=False)
    assert isinstance(configure_logging_from_env(), list)

def test_sanitize_call_site():
    assert sanitize_log_data({"secret": "s"})["secret"] == "[REDACTED]"
```

- [ ] **Step 2: Run to verify it fails** — run first; fix any 0.3.x drift surfaced (this is the compat gate).

- [ ] **Step 3: Implement** CI + Makefile.

In `.github/workflows/ci.yml` add (pin `actions/*` to full SHAs per repo convention):

```yaml
  python-utils-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@<full-sha>
      - uses: actions/setup-python@<full-sha>
        with: { python-version: "${{ matrix.python-version }}" }
      - run: pip install -e 'packages/python-utils[dev]'
      - run: cd packages/python-utils && pytest tests/ -m "not integration" -v
      - run: cd packages/python-utils && mypy --strict src/penguintechinc_utils/telemetry
```

Confirm `pyproject.toml` keeps `--cov-fail-under=90`. In `Makefile`, the existing `python-utils && pytest tests/ -v` line inherits coverage from pytest config; add a mypy line for `telemetry/`.

- [ ] **Step 4: Verify gates actually fail on purpose** — temporarily drop a `telemetry/` line's coverage or break a type; confirm the job goes red; revert. (Verification Integrity: a gate that can't fail is not a gate.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_consumer_compat.py .github/workflows/ci.yml Makefile
git commit -m "ci(python-utils): 3.11/3.12/3.13 test job, coverage + mypy gates, consumer compat"
```

---

## Post-plan

- Update `packages/python-utils/README.md` with the `init()` quickstart and the "logs-only vs full telemetry" distinction (fold into Task 12's commit if preferred).
- Open the PR into `release/python-utils/v0.4.x` only when the green gate is met (coverage ≥90%, all CI green, telemetry validation counts printed non-zero) — see `merging-to-release` skill.
- **0.3.1 PII-leak patch release is independent** and can ship first from `release/python-utils/v0.3.x`; if it merges, Task 2's redaction change rebases to a near no-op.
- **Rust port** is a separate spec + plan; it reuses `tests/vectors/sanitizer_vectors.json` and this env-var/`init()` contract.
