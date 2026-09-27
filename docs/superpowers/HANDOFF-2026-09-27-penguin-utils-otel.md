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
| **15 — redact_text hardening (added mid-plan)** | ⚠️ **IN PROGRESS — 1 known defect, see below** |
| 6 — trace-context structlog processor | ⬜ not started (brief pre-extracted) |
| 7 — rewire logging.py onto stdlib | ⬜ not started |
| 8 — fault-isolated + async sink dispatch | ⬜ not started |
| 9 — KillKrill flush off caller thread | ⬜ not started |
| 10 — ASGI/httpx/sqlalchemy/redis instrumentation | ⬜ not started |
| 11 — get_tracer / get_meter / timed | ⬜ not started |
| 12 — init() + Telemetry handle + exports | ⬜ not started |
| 13 — integration test vs real collector + redaction proof | ⬜ not started (**run after 15**) |
| 14 — consumer compat + CI job + coverage/mypy gates | ⬜ not started |

Suite at pause: **139 tests passing**, coverage ~96.4% (`logging.py` 100%). Gate `--cov-fail-under=90` active.

## ⚠️ FIRST JOB: finish Task 15 (a real secret leak)

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

## Deferred minors (triage at final whole-branch review)

- Sanitized span copy reports `dropped_attributes`/`dropped_events` as 0.
- Deprecated `instrumentation_info` not carried onto the span copy (`instrumentation_scope` is).
- Bare (non-dict) string `extra=` values on log records aren't sanitized (matches Task 5's brief scope).
- Span fail-closed is whole-mapping granularity (safe direction, coarser than the log handler's per-field).
- `sanitize_log_data` returns a `list` for `tuple`/`set` input (type change, intentional).
- `packages/python-utils/src/penguin_utils.egg-info/` is a tracked stale build artifact — should be git-ignored.
- `telemetry/config.py` may have `mypy --strict` findings (Task 3 didn't gate mypy; Task 14 gates the whole `telemetry/` dir).

## Environment notes

- Install before any OTel-touching task: `cd packages/python-utils && pip install -e '.[dev]'` (no sudo). A fresh agent's venv will NOT have OTel and `test_otel_imports_are_available` will fail until it does.
- Never import `opentelemetry.sdk._logs.LoggingHandler` (deprecated in 1.44.0) — use `opentelemetry.instrumentation.logging.handler.LoggingHandler`.
- Tests needing a collector are marked `integration` (Task 13 adds them); default runs exclude them.
- Commit trailers required on every commit:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` and `Claude-Session: <session url>`.
- **Do not merge to `main`** — release→main is always user-gated. Feature→release auto-merge only when fully green.
