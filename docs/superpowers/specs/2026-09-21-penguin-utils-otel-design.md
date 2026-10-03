# penguin-utils 0.4.0 — logging + OpenTelemetry in one call

**Status:** approved design, not yet implemented
**Date:** 2026-09-21
**Package:** `packages/python-utils` (PyPI `penguin-utils`, import `penguintechinc_utils`)
**Follow-up:** a Rust crate mirroring this design — separate spec

## Goal

`pip install penguin-utils` plus one call gives a service sanitized structured logging **and** OTel
logs, traces and metrics over an env-configurable OTLP endpoint. No per-service boilerplate, no
optional extra to remember.

OTel is a **required** dependency, not an extra: "for sure" is the requirement.

## Current state (0.3.0, published)

| Fact | Consequence |
|---|---|
| structlog configured with `PrintLoggerFactory` (`logging.py:146`) | Output never reaches stdlib `logging`, so an OTel handler would see nothing |
| No package in the repo imports `opentelemetry` | Every consumer hand-rolls its own setup |
| `level=` never filters (`:150`, `:164`) | DEBUG always prints |
| Sink dispatch has no try/except (`:105-107`) | One failing sink raises into the caller's log call and skips the rest |
| KillKrill flushes on the caller's thread (`killkrill.py:93`) | A log call can stall ~3xtimeout+3s |
| `EMAIL_REGEX.match` anchors at index 0 (`:47,74`) | An email mid-string leaks — fixed in the pending 0.3.1 |
| No coverage gate; CI runs only ruff/bandit/pip-audit | The 90% rule is unenforced here |
| `pydal` required but never imported | Dead dependency |

Consumers: gough and license-server (`get_logger`), elder (`sanitize_log_data`), penguincloud
(`get_logger`, `SanitizedLogger`). elder, nest, waddleai and waddlebot each hand-roll OTel;
elder's log bridge never attaches a handler, so its logs never reach OTel at all.

## 1. Public API

```python
from penguintechinc_utils import init, get_logger

tel = init()                 # zero-arg: everything from env
tel = init(app=quart_app)    # + ASGI request spans and latency histogram
log = get_logger(__name__)   # unchanged 0.3.x signature
```

Precedence: explicit argument > env var > default.

| Arg | Env | Default |
|---|---|---|
| `service_name` | `OTEL_SERVICE_NAME` | one WARN, then `unknown_service:<argv0>` |
| `service_version` | — | `__main__` package version if resolvable |
| `level` | `LOG_LEVEL` | `INFO` |
| `log_format` | `LOG_FORMAT` | `json` when stdout is not a TTY, else `console` |
| `app` | — | `None` |
| `sinks` | `LOG_CLOUDWATCH_*`, `LOG_GCP_*`, `LOG_KAFKA_*` (unchanged) | 0.3.x sinks still work |
| — | `OTEL_EXPORTER_OTLP_{ENDPOINT,PROTOCOL,HEADERS,TIMEOUT}`, `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_SDK_DISABLED` | read natively by the SDK; protocol defaults to `grpc` |

- **Endpoint unset or `OTEL_SDK_DISABLED=true`:** console logging works, trace/span IDs still
  appear, nothing is exported, one WARN. No crash, no connection attempt.
- **Second `init()`:** returns the same handle plus a WARN; never stacks handlers.
- **`tel.shutdown()`:** flushes all three signals; also registered with `atexit`.
- **Helpers:** `get_tracer(name)`, `get_meter(name)`, and `timed("op.name")` (decorator or context
  manager) recording a span plus a duration histogram — satisfies histograms-first.
- **Unchanged:** `configure_logging()`, `configure_logging_from_env()`, `sanitize_log_data()`,
  `SanitizedLogger`, every sink class, `decorators.py`. `configure_logging()` stays logs-only.

## 2. Structure and data flow

```
penguintechinc_utils/
|- __init__.py        + init, get_tracer, get_meter, timed; __version__ from package metadata
|- logging.py         rewired onto stdlib (LoggerFactory + ProcessorFormatter); API unchanged
|- sinks.py           unchanged classes; dispatch moves into a fault-isolated handler
|- killkrill.py       flush always on its background thread
|- decorators.py      0.3.0 decorator factory, untouched
`- telemetry/
   |- __init__.py     init() + Telemetry handle (@dataclass(slots=True))
   |- config.py       TelemetryConfig: arg > env > default, validated
   |- providers.py    Resource + Tracer/Meter/LoggerProvider + OTLP exporters (grpc | http)
   |- bridge.py       SanitizingLogHandler + SanitizingSpanExporter (only file importing sdk._logs)
   |- context.py      structlog processor adding trace_id / span_id
   |- instrument.py   ASGI wrap for app=; httpx / SQLAlchemy / Redis if importable
   `- helpers.py      get_tracer, get_meter, timed
```

```
get_logger().info(...) -> structlog chain: logger name -> level -> timestamp -> trace ids -> sanitize
                                  |
quart / hypercorn / httpx -> stdlib root logger (level from init) <-+
                                  |- ConsoleHandler       json | console
                                  |- SanitizingLogHandler -> BatchLogRecordProcessor -> OTLP
                                  `- LegacySinkHandler    0.3.x sinks, each isolated
spans   -> BatchSpanProcessor -> SanitizingSpanExporter -> OTLP
metrics -> PeriodicExportingMetricReader -> OTLP
```

- **Sanitize twice.** Once in the structlog chain, once in the OTel log handler. Third-party
  libraries log through stdlib and never pass through structlog; the second pass is the only thing
  that catches them.
- **Spans are sanitized too.** The ASGI instrumentor records request URLs, where `?token=` appears.
  The exporter wrapper redacts sensitive keys/values in span attributes and events before export.
  Metric labels come only from instrumentor-defined, non-PII attributes.
- **No feedback loops.** `opentelemetry.*` and `grpc` loggers are excluded from the OTel handler and
  floored at WARNING, so exporter errors can never re-enter the exporter.
- **One sanitizer**, driven by a shared test-vector file that the Rust port will also be tested against.
- **`LoggingHandler` source.** The SDK's handler is deprecated in 1.44.0
  (`sdk/_logs/_internal/__init__.py:580`, changelog PR #4919). `bridge.py` wraps
  `opentelemetry.instrumentation.logging.handler.LoggingHandler(logger_provider=...)` instead, so
  consumers see no DeprecationWarning. Trace IDs still come from our structlog processor; that
  package's log-record-factory patching stays off.
- **Duplicate guard.** Under the `opentelemetry-instrument` auto-launcher an OTel handler may
  already be on the root logger. `init()` then skips adding its own and wraps the existing one with
  sanitization, so logs are neither doubled nor un-redacted.

### Dependencies (all 2026-07-16 unless noted)

| Dependency | Spec | Why |
|---|---|---|
| `opentelemetry-api`, `-sdk` | `>=1.44.0,<2` | the three providers |
| `opentelemetry-exporter-otlp-proto-grpc`, `-proto-http` | `>=1.44.0,<2` | both protocols without reinstalling; grpc pulls grpcio 1.83.1 |
| `opentelemetry-instrumentation-logging` | `>=0.65b0,<1` | the non-deprecated stdlib->OTel handler |
| `opentelemetry-instrumentation-asgi`, `-httpx`, `-sqlalchemy`, `-redis` | `>=0.65b0,<1` | penguin-dal wraps SQLAlchemy (`db.py:130`, async at `:503`); dal, aaa and limiter use Redis. Each activates only if the target library is importable |
| `structlog` | `>=23.0` (unchanged) | `ProcessorFormatter` is long-standing; raising the floor buys nothing |
| `requires-python` | `>=3.11` (unchanged) | a library floor is not a service floor; raising it would hard-break a consumer's install. Services still run 3.13. CI tests 3.11/3.12/3.13 |
| `pydal` | kept, unused | dropping it is a breaking change for anything relying on it transitively; remove at 1.0 |

Ranges rather than exact pins: exact pins in a library clash with consumers that pin OTel
themselves (elder, nest, waddleai all do). Exact hashes live in our CI lock file and in each
consuming app's `requirements.txt`, which is where the pinning rule applies. The contrib packages
pin `semantic-conventions==0.65b0`, which pins `api==1.44.0`, so pip still resolves a matched set.

`grpcio` has no musl wheels. Not a concern: we ship Debian slim only.

## 3. Failure handling

Telemetry failure is never an app failure, and redaction failure never leaks raw data.

| Failure | Behaviour |
|---|---|
| Collector down or slow | Export only on SDK background threads, bounded queues (drop when full), timeout from `OTEL_EXPORTER_OTLP_TIMEOUT`. A log/span/metric call never blocks on the network |
| Exporter error messages | On `opentelemetry.*` loggers, excluded from export, console WARN at most once per 60s |
| Endpoint unset / SDK disabled | No exporters, one WARN; trace IDs, spans and meters still work in-process |
| Bad env value | WARN naming the variable and the fallback; **never raise** |
| Bad argument in code | `TypeError` / `ValueError` from `init()` — env comes from ops and must not crash; args come from code and should |
| Sanitizer throws | **Fail closed:** value becomes `[REDACTED:sanitize-error]`, rest of the record ships |
| A legacy sink throws | Isolated per sink; other sinks run; call returns. Counted in `penguin_utils.log_sink.errors` (labelled by sink class) plus a rate-limited stderr line |
| Network sinks block the caller | CloudWatch/GCP/Kafka/KillKrill move behind one bounded queue with a background thread, dropping oldest when full (`penguin_utils.log_sink.dropped`). Stdout/File/Callback stay synchronous so consumers' tests that assert on `CallbackSink` still pass |
| Process exit, dead collector | `atexit` flush with a hard 5s budget; exit never hangs |
| Pre-fork servers | Documented: call `init()` in the worker. SDK at-fork reinitialisation is relied on and covered by a test |

**Feature-flag exception.** The library is not wrapped in a PostHog flag. It activates only when a
service calls `init()`, and flag checks would need working telemetry to report their own failures —
circular. Flag gating stays with the consuming apps' features.

## 4. Compatibility, release, testing

Every 0.3.x symbol keeps its name, signature and return type; an API-contract test asserts this with
`inspect.signature`.

Three deliberate behaviour changes, each a CHANGELOG entry:

1. `level` is enforced — DEBUG lines that printed regardless stop appearing unless `LOG_LEVEL=DEBUG`.
2. A failing sink no longer raises into the caller's log call.
3. CloudWatch/GCP/Kafka/KillKrill deliver asynchronously.

### Release plan

1. **0.3.1 first** — the in-string email redaction fix on `fix/utils-log-redaction`. It is a live PII
   leak; without a patch release the only way to get it is the whole 0.4.0 upgrade. Cut
   `release/python-utils/v0.3.x` from tag `penguin-utils-v0.3.0`, cherry-pick `ccac86e`, tag
   `penguin-utils-v0.3.1`, publish.
2. **0.4.0 next** — `release/python-utils/v0.4.x` off `main`, merge 0.3.1 in, `feature/utils-otel`
   off that. 0.3.0 is tagged and on PyPI, so a minor bump is allowed.

Version currently lives in three unsynced files; 0.4.0 makes `pyproject.toml` the single source,
`__version__` reads package metadata, and a test asserts `.version` matches.

### Testing

68 tests today, no coverage gate, and CI does not run them for this package.

| Layer | What |
|---|---|
| Unit | Config precedence, sanitizer vectors, bridge redaction, every failure row above, idempotent `init()`, duplicate-handler guard, fork safety |
| Integration | Pinned `otel/opentelemetry-collector-contrib:0.144.0` with the file exporter; assert logRecords >=1, metrics >=1, **histogram >=1**, spans >=1, printing every count |
| Redaction proof | Plant an email and a token; assert **0** occurrences in exported JSON **and** that a non-sensitive marker is present — without the marker a broken exporter passes by exporting nothing |
| Consumer compat | Install the built wheel in a clean venv; run the real 0.3.x usage from gough, elder, penguincloud, license-server |
| Gates | `fail_under=90`, mypy --strict on `telemetry/`, a CI job that actually runs these on 3.11/3.12/3.13 |

Tests must set `OTEL_METRIC_EXPORT_INTERVAL` low; the 60s default exports nothing inside a smoke
test window.

### Risk

~20 new transitive dependencies reach every consumer, widening the `pip-audit` surface. Accepted:
the alternative is every service continuing to hand-roll OTel, which is how elder ended up with a
log bridge that silently exports nothing.

## Follow-up: Rust crate

Separate spec. `testing.md` currently has Rust asserting `tracing` because no penguin logging crate
exists; the port closes that gap. It reuses this env-var contract, the `init()` shape, and the same
sanitizer test vectors so both implementations redact identically.
