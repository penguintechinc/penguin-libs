# Handoff — penguin-utils 0.4.0 (logging + OpenTelemetry)

**Date:** 2026-09-27 · **Branch:** `feature/utils-otel` → `release/python-utils/v0.4.x`
**Why this file exists:** the subagent-driven-development ledger lives in `.superpowers/sdd/` which is
**git-ignored**, so every ruling and status note below is reproduced here to survive the handoff to a
new (cloud) session. Read this before touching code.

## Documents

| What | Path |
|---|---|
| Design spec (approved) | `docs/superpowers/specs/2026-09-21-penguin-utils-otel-design.md` |
| Implementation plan (15 tasks) | `docs/superpowers/plans/2026-09-25-penguin-utils-otel.md` |
| Process | superpowers:subagent-driven-development (fresh implementer per task → task review → scoped re-review, max 5 fix rounds) |

## Status

| Task | State |
|---|---|
| 1 — deps + single-source version 0.4.0 | ✅ complete, review clean |
| 2 — sanitizer hardening + shared vectors | ✅ complete (1 fix round: `is_sensitive_key` contiguous-subsequence regression) |
| 3 — TelemetryConfig (arg>env>default) | ✅ complete (1 fix round: missing `log_format` asymmetry tests) |
| 4 — OTel providers (graceful no-endpoint) | ✅ complete (1 fix round: test honesty + docstrings/type hints) |
| 5 — bridge: sanitizing log handler + span exporter | ✅ complete, review clean for its own diff |
| **15 — redact_text hardening (added mid-plan)** | ✅ complete (`947411e`) — 2 review rounds, 4 further leaks + 2 DoS shapes closed |
| 6 — trace-context structlog processor | ✅ complete (`f771a18`) |
| 7 — rewire logging.py onto stdlib | ✅ complete (`1a4ecf9`), review PASS |
| 8 — fault-isolated + async sink dispatch | ✅ complete (`55b9960`) |
| 9 — KillKrill flush off caller thread | ✅ complete (`e7c0533`) — 2 review Criticals fixed (shutdown budget, client-close race) |
| 10 — ASGI/httpx/sqlalchemy/redis instrumentation | ✅ complete (`1ae0f70`), review PASS |
| 11 — get_tracer / get_meter / timed | ✅ complete (`274586b`) — 2 review Importants fixed (async timing, thread-safety test) |
| 12 — init() + Telemetry handle + exports | ✅ complete (`b45812a`) |
| 13 — integration test vs real collector + redaction proof | ✅ complete (`462cf27`) — 3 tests green vs a live collector |
| 14 — consumer compat + CI job + coverage/mypy gates | ✅ complete (`e20de37`) |
| — pre-existing lint + stale egg-info | ✅ chore (`917267a`) |

**All 15 tasks complete.** Suite: **265 unit tests passing, 3 integration passing**,
coverage **97.83%** (`logging.py`, `telemetry/*` all 100% except config.py 96%).
`ruff check`, `ruff format --check`, `mypy --strict src/penguintechinc_utils/telemetry`
and `bandit` all clean. Integration counts printed non-zero:
`logRecords=1 metrics=2 histograms=2 spans=1` (http) and `logRecords=1 metrics=2 spans=1` (grpc).

**Not done, deliberately:** no PR opened and nothing merged — release→main is user-gated
and the feature→release merge decision is left to the human.

## ✅ Task 15 (the secret leak) — RESOLVED

Fixed in `947411e`. The section below is retained as the original problem statement;
the invariant table is now an executable gate in `tests/test_sanitizer.py`
(`test_invariant_secret_never_survives` / `test_invariant_benign_text_unchanged`), and
every row holds. Two review rounds found four MORE live leaks and two denial-of-service
shapes beyond the reported defect — see rulings 10-13.

## ⚠️ ORIGINAL PROBLEM STATEMENT: Task 15 (a real secret leak)

`packages/python-utils/src/penguintechinc_utils/logging.py` — `_KV` has two alternatives. The
`key=value` branch is correct. The **second (`key: value`, colon-space) branch still carries the
negative lookahead** `(?![A-Za-z0-9_.\-]+\s*[:=])`, so an `=`-containing value in that form is not
redacted at all.

Verify with:
```bash
cd packages/python-utils && PYTHONPATH=src python3 -c "
from penguintechinc_utils.logging import redact_text as r
for c in ['token: YWJjMTIz==','secret: abcdef==','token=YWJjMTIz==','Authorization: Bearer abc123']:
    print(repr(c),'->',repr(r(c)))"
```
Current (bad) output — first two leak:
```
'token: YWJjMTIz=='  -> 'token: YWJjMTIz=='      # LEAK
'secret: abcdef=='   -> 'secret: abcdef=='       # LEAK
'token=YWJjMTIz=='   -> 'token=[REDACTED]'       # ok
'Authorization: Bearer abc123' -> 'Authorization: [REDACTED]'  # ok
```
**Fix:** remove the lookahead from the colon-space branch; bound its value as the first branch does
(`(?:Bearer|Basic|Digest|Token)\s+[^\s&#,;]+|[^\s&#,;?]+`). Do NOT add a second sensitive-word list —
sensitivity is decided by `is_sensitive_key` only.

Invariants that must ALL hold after the fix (these are the gate):

| Input | Expected |
|---|---|
| `token: YWJjMTIz==` / `secret: abcdef==` | value fully redacted |
| `token=YWJjMTIz==`, `?api_key=c2VjcmV0==&x=1`, `password=P@ss==word`, `token=ab/cd+ef==` | value fully redacted |
| `?token=sk-live-abc123&user=bob` | token gone; `user`/`bob` survive |
| `https://api.x/v1?api_key=sk-LIVE-1` | key value gone; URL not swallowed whole |
| `Authorization: Bearer abc123` | `abc123` fully gone |
| `note: password=hunter2 error` | `hunter2` gone; `error` survives |
| `tokenizer=gpt2`, `authorized=true`, `?page=2&sort=name`, `time=12:30` | UNCHANGED (no over-redaction) |
| emails anywhere | `[email]` |

Then: add a shared vector for the colon-space base64 case, run `pytest tests/ -v` (incl.
`test_bridge.py`, whose span redaction inherits this), `ruff check`, `mypy --strict`.

## Rulings made so far (each with cost-if-wrong)

1. **T13 redaction proof reshaped** — token probe uses a sensitive-key field + a URL `?token=` probe, not a bare free-text token. *Why:* `redact_text` guarantees emails + sensitive `key=value`, not arbitrary tokens in prose. *Cost:* proof covers a narrower guarantee; widening is a regex + vector.
2. **T7→T8 forward reference accepted** — T7's `configure_logging` references `_LegacySinkHandler` defined in T8; plan mandates guard-in-T7 / restore-in-T8. *Cost:* T7 review may flag an unresolved name; fixed one task later.
3. **T2 `is_sensitive_key` = contiguous segment subsequence** (not set intersection). *Why:* set intersection missed `stripe_api_key`, `user_session_id` — a regression vs the old substring match. *Cost:* minimal; stricter than substring, keeps `footprint`/`tokenizer` benign.
4. **`redact_text`/`is_sensitive_key` NOT exported at top level** — intra-package helpers consumed via `from ..logging import`. Only `init`/`get_tracer`/`get_meter`/`timed` are new public API. *Cost:* none.
5. **OTLP exporters stay argument-free (env-native)** — do NOT pass `endpoint=`. *Why:* spec says these `OTEL_*` vars are read natively by the SDK; `init()` has no non-env endpoint param; and passing `endpoint=` breaks the **http** exporter, which only gets the per-signal path (`/v1/traces`…) appended when reading the env var. *Cost:* if `init()` later takes an explicit endpoint, revisit.
6. **T5 span-copy deviation accepted** — build new `ReadableSpan`/`Event` copies instead of the plan's in-place `span._attributes` mutation. *Why:* verified in SDK source that `Span.end()` hands ONE `ReadableSpan` to every registered processor; in-place mutation would corrupt others. *Cost:* the copy reports `dropped_attributes`/`dropped_events` as 0 (plain dict/tuple, not `Bounded*`).
7. **T5's query-string gap → new Task 15** rather than blocking T5 — the defect was in `redact_text` (T2's file), not T5's diff. *Cost:* none; tracked as Task 15.
8. **T15 redesign: `redact_text` scans `key=value` and decides via `is_sensitive_key`** — one shared key judgment, no second word list. *Why:* fixes the leaks while keeping precision (`tokenizer=`, `authorized=`, `design=` stay untouched). *Cost:* intricate regex; the invariant table above is the gate.
9. **T15 round 2: remove the lookahead; value allows `=`,`/`,`+` but stops at `?`** so base64 redacts whole while URL query params stay delimited. *Cost:* a value legitimately containing `?` would truncate (rare, and safe direction).

### Rulings 10-24 (second session, Tasks 15 + 6-14)

10. **`_KV` replaced by a separator-driven scan** (`_SEP_FIND` + `_KEY_END` + `_VALUE`).
    *Why:* review found three further live leaks the single regex could not reach —
    `token := secret` (a one-char separator left the secret outside the match),
    `token:\nsecret`, and `{"token": "secret"}` (a quoted JSON key was invisible). The
    separator now absorbs a `[:=]+` run plus a gap that may cross a newline, and the key
    class accepts optional surrounding quotes — `is_sensitive_key` splits on
    non-alphanumerics, so quotes fall out of the judgement for free and there is still
    no second word list. *Cost:* a value legitimately starting with `=`/`:` loses those
    characters; never a leak, since the key decides.
11. **The sensitive-value class is deliberately permissive** (`[^\s&#,;]+`), with trailing
    structural characters trimmed back off and re-emitted after the placeholder.
    *Why:* excluding quotes and brackets is how `token=""secret""` and
    `{"token": "\"secret\""}` escaped whole. For a key already judged sensitive,
    over-redaction is the safe direction. Trimming keeps JSON parseable. *Cost:* a
    sensitive value containing `?` or a bracket may over-redact slightly.
12. **`redact_text` scans with an explicit cursor; a benign key's value is never matched.**
    *Why:* recursion blew CPython's C stack on a ~1000-link `k=k=...=token=secret` chain
    (contained only by callers' try/except, which destroyed the whole field); and matching
    a benign key's value greedily on every iteration was quadratic — 7.8s for an 80KB
    message of chained `k=` pairs. Now linear (90ms), verified by a ratio gate that
    rejects the old shape at 68.6x. *Cost:* none known.
13. **Pre-existing quadratic in `EMAIL_REGEX` fixed by RFC-5321 bounds, NOT a lookbehind.**
    *Why:* an unbounded greedy local part retried at every offset of any long alphanumeric
    run — a 40KB base64 blob or stack trace cost ~2.2s per call, shipped since 0.3.x. A
    lookbehind looked cheaper and was **proven unsafe**: it tests the raw string rather
    than what a prior match consumed, so `a@b.coma.b@x.co` leaked the second address in
    full. `{1,64}`/`{1,255}` are the RFC limits, so no real address stops matching.
    *Cost:* a >64-char local part keeps its prefix (the domain still redacts).
14. **`is_sensitive_key` is memoised**, keyed on `(key, SENSITIVE_KEYS)`. *Why:* it
    re-split the whole word list on every call and dominated redaction cost. Keying on the
    frozenset means replacing `SENSITIVE_KEYS` is still honoured. *Cost:* none.
15. **Task 6: `add_trace_context` gates on `ctx.is_valid` AND `span.is_recording()`**, per
    the plan's Interfaces prose over its code sample. *Cost:* a sampled-out span logs
    without ids — preferable to ids linking to a trace the backend never received.
16. **Task 6 tests use a local `TracerProvider` + `trace.use_span`**, not
    `trace.set_tracer_provider`. *Why:* the global provider is one-shot per process, so
    claiming it in a test silently prevents `init()` from installing its own. *Cost:* none.
17. **Task 7: `get_logger`'s `level` default moves INFO → None** (and `name` becomes
    optional). *Why:* unconditionally pinning a per-logger level is exactly what made
    0.3.x print DEBUG regardless of config, and it would override the root level that
    spec §4 change 1 requires. Every consumer call shape still works (asserted).
    *Cost:* a consumer relying on `get_logger(name)` to pin INFO loses that side effect —
    which is the documented behaviour change.
18. **Task 7: the plan's `isinstance(get_logger(...), stdlib.BoundLogger)` assertion became
    `isinstance(get_logger(...).bind(), ...)`.** *Why:* `structlog.get_logger` returns a
    `BoundLoggerLazyProxy`, which the existing 0.3.x contract test asserts; changing the
    return type would break consumers. `.bind()` resolves the real wrapper.
19. **Task 7 keeps `_SinkProcessor` as the guard for Task 8's forward reference**, rather
    than the plan's `pass`. *Why:* `pass` would have left the existing sink tests red until
    Task 8, breaking the run-the-suite-before-every-commit gate. *Cost:* sink dispatch is
    described in two places across two commits, never active in both.
20. **Task 7: `add_trace_context` imported lazily inside `_shared_processors`.** *Why:*
    `telemetry/__init__` imports back into `logging`, so a module-level import is a cycle.
    Also added `tests/conftest.py`, restoring root handlers + structlog config after every
    test, because `configure_logging` now owns the root handler set.
21. **Task 9: `KillKrillConfig(api_key=...)` is required**, so the plan's test passes a
    dummy rather than giving `api_key` a default (a default changes a published signature).
    `test_eager_flush_when_batch_full` became a poll — it only held because `emit` flushed
    inline, the exact behaviour Task 9 removes.
22. **Task 9: `close()` takes one hard deadline (default 5s) and will not close the shared
    httpx client while the worker is alive.** *Why:* review Criticals. With default config
    an unreachable endpoint costs 10+1+10+2+10s per attempt, so an 11s join plus an
    unconditional final flush could hang process exit ~44s; and closing the client
    mid-request raises an error `_deliver_with_retry` does not catch, killing the worker
    silently. *Cost:* past the deadline the buffered batch is dropped with a WARN.
23. **Task 10: `instrument()` returns the ORIGINAL app when ASGI wrapping fails**, not
    `None` — `None` would silently drop the caller's app.
24. **Task 11: `timed` resolves providers per invocation, overrides `_recreate_cm`, and
    handles `async def` explicitly** (plus `__aenter__`/`__aexit__`). *Why:* the plan's
    eager-histogram/single-`_span_cm` sketch shares mutable state across reuse, nesting and
    threads; and `ContextDecorator.__call__` times only coroutine *creation*, so `@timed` on
    an `async def` reported ~0ms for a 200ms await — silently wrong latency data.
    Documented limitation: one instance reused for *nested* `with` blocks is unsupported.
25. **Task 12: the duplicate-handler guard snapshots the pre-existing OTel handler BEFORE
    `configure_logging`**, which owns and clears the root handler set; the deprecated
    handler class is detected by module+class name, never imported. The OTel handler also
    gets a JSON `ProcessorFormatter` (without one, `record.getMessage()` yields a Python
    dict repr as the OTLP body) and a filter excluding `opentelemetry.*`/`grpc`.
26. **Task 12: structlog's private record attributes are hidden during OTel translation.**
    *Why:* `LoggingHandler` copies every non-reserved record attribute into OTLP attributes,
    and structlog attaches `_logger` — a logger object — so OTel rejected it and warned on
    every single log line. Task 5's synthetic-record tests could not surface this.
    Also: re-exporting the `instrument` function shadowed the `telemetry.instrument`
    submodule, now bound privately.
27. **Task 13: the plan's span counter key `resourceTraces` does not exist** — the real
    OTLP-JSON key is `resourceSpans`. Verified against collector 0.144.0. Left as written it
    would have counted zero spans forever while the other assertions stayed green: a gate
    that cannot fail. Each case also emits from a **fresh subprocess**, because OTel's
    global providers are one-shot per process, so a second `init()` sends telemetry through
    the first (shut down) provider — which made the grpc case pass or fail on collection
    order alone.
28. **`telemetry/config.py`'s `mypy --strict` gaps fixed in Task 12**, not deferred to 14,
    so the whole `telemetry/` package passes the gate from that commit onward.

## Deferred minors (triage at final whole-branch review)

- Sanitized span copy reports `dropped_attributes`/`dropped_events` as 0.
- Deprecated `instrumentation_info` not carried onto the span copy (`instrumentation_scope` is).
- Bare (non-dict) string `extra=` values on log records aren't sanitized (matches Task 5's brief scope).
- Span fail-closed is whole-mapping granularity (safe direction, coarser than the log handler's per-field).
- `sanitize_log_data` returns a `list` for `tuple`/`set` input (type change, intentional).
- ~~`packages/python-utils/src/penguin_utils.egg-info/` is a tracked stale build artifact~~ — **fixed** in `917267a` (untracked; `*.egg-info/` was already ignored).
- ~~`telemetry/config.py` may have `mypy --strict` findings~~ — **fixed** in `b45812a`; the whole `telemetry/` dir passes `mypy --strict`.

### Added by the second session (all non-blocking, none a leak)

- **YAML block scalars are not redacted** — `token: |` followed by indented secret lines
  only redacts the `|` indicator. Out of reach for a single-line key/value scanner;
  asserted in `test_yaml_block_scalar_is_a_documented_limitation` so the gap is explicit
  and fails loudly if behaviour changes, rather than being silently assumed covered.
- **Unicode lookalike separators bypass detection** — fullwidth `：` (U+FF1A) and ratio
  `∶` (U+2236) are not recognised, so `token：secret` passes through. Would need NFKC
  normalisation before scanning.
- **Multi-pair headers redact only the first pair** — `cookie: a=1; b=2` becomes
  `cookie: [REDACTED]; b=2` (the value stops at `;`). Strictly better than 0.3.x, which
  redacted none of it, but `b=2` survives.
- **A `>128`-character key is judged on its last 160 characters** (`_MAX_KEY_SPAN`), which
  is the end carrying the sensitive word, so no practical difference.
- **`AsyncSink` threads are not reclaimed when `configure_logging` is called again** — the
  handler is removed but its wrapper threads stay. Bounded (one per network sink per call),
  daemon, and `configure_logging` is a startup call, so this leaks nothing in practice.
- **`mypy --strict` on `sinks.py` reports a missing `boto3` stub** (pre-existing; boto3 is
  an optional extra). Not in the gate set, which covers `telemetry/` only.
- **The OTLP log body is the full rendered JSON line**, so severity/timestamp appear both in
  the body and in OTLP's own fields. The ideal shape is `body = message` with the rest as
  attributes; that needs custom translation.
- **`timed` reuse for *nested* `with` blocks on one instance is unsupported** (the decorator
  path is safe — it gets a fresh instance per call).

## Environment notes

- **System pip is externally managed (PEP 668) and `pip3` maps to python3.12.** Create a venv
  with the uv-managed 3.13 instead: `cd packages/python-utils && uv venv --python 3.13 .venv`
  then `uv pip install --python .venv/bin/python -e '.[dev]'`. `.venv/` is already gitignored.
  Run everything through `.venv/bin/python` — never bare `python3`/`pip`.
- Integration tests need docker. The collector image is pre-pulled as
  `otel/opentelemetry-collector-contrib@sha256:213886eb6407af91b87fa47551c3632be1a6419ff3a5114ef1e6fc364628496f`
  (tag 0.144.0) and the fixture publishes on host ports 14317/14318 to avoid colliding with a
  local collector.
- Install before any OTel-touching task: `cd packages/python-utils && pip install -e '.[dev]'` (no sudo). A fresh agent's venv will NOT have OTel and `test_otel_imports_are_available` will fail until it does.
- Never import `opentelemetry.sdk._logs.LoggingHandler` (deprecated in 1.44.0) — use `opentelemetry.instrumentation.logging.handler.LoggingHandler`.
- Tests needing a collector are marked `integration` (Task 13 adds them); default runs exclude them.
- Commit trailers required on every commit:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` and `Claude-Session: <session url>`.
- **Do not merge to `main`** — release→main is always user-gated. Feature→release auto-merge only when fully green.
