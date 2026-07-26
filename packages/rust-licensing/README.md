# penguin-licensing (Rust)

PenguinTech license entitlement + PostHog-compatible feature-flag client for
Rust services, backed by `license.penguintech.io` (one server, two concerns:
PostHog CE flag evaluation and license entitlement).

Rust port of the `penguin-licensing` PyPI package semantics.

## Behavior

- **Entitlement**: `POST /api/v2/validate` (Bearer `LICENSE_KEY`) → tier
  (`free`/`professional`/`enterprise`, `community` accepted as `free`) +
  per-feature entitlements. 5-minute snapshot cache, lock-free reads.
- **Flags**: PostHog `/decide?v=3` at `POSTHOG_HOST` with `POSTHOG_KEY`.
  Flag keys follow `{product}.{feature-name}`; flags default **OFF**.
  The license key is **never** sent to the PostHog host — the bearer
  credential is attached per-request to license-server calls only.
- **Enforcement is always on.** There is no environment variable, CLI flag,
  or build profile that disables license checking.
- **Domain bypass** (the only bypass): deployments on `*.penguincloud.io`,
  `*.penguintech.cloud`, plus product `.app` domains registered in code via
  `with_bypass_domain`, evaluate everything as enabled. The deployment
  domain itself is set in code (`with_deployment_domain`) and is **never**
  read from the environment — see [Environment](#environment).
- **Fail-closed by default**: the cached snapshot is replaced with
  community tier — **and cached flags are dropped** — on any license-server
  response that is neither a success nor an outage. That covers explicit
  refusals (`401`/`403`/`404`, revoked or unknown key) and equally anything
  unexpected (`400`, `418`, a stray `3xx`). `expires_at` is enforced too —
  past `expires_at + offline_grace` (default **72h**) gating drops to
  community.
- **Graceful degradation on outage**: transport errors and exactly
  `5xx`/`408`/`429` keep serving the last cached snapshot; nothing cached →
  community tier, flags OFF. Gating reads never error and never panic.
  Retention is an **allowlist**: a status not on that list fails closed
  rather than silently continuing to grant Enterprise.
- **Non-blocking reads**: `check_feature` / `flag_enabled` / `tier` never
  perform inline network I/O. They serve the current snapshot and schedule
  a single-flight background refresh when it is stale, with exponential
  backoff so an unreachable server cannot cause a fetch per request.
- **HTTPS required**: `LICENSE_SERVER_URL` and `POSTHOG_HOST` must be
  `https://`; plain `http://` is accepted only for `localhost`/loopback.
- **Keepalive**: `POST /api/v2/keepalive` with the server-assigned id,
  driven by the background refresh loop.

## Runtime requirement

**Tokio is required.** `spawn_refresh` and the single-flight background
refresh triggered by stale gating reads are spawned onto the ambient Tokio
runtime handle (`rt` + `time` features). Under a non-Tokio executor the
background refresh is skipped silently — gating reads still work, but the
caller must drive `refresh()` itself.

Call `refresh()` once at startup before serving traffic: until the first
successful fetch, everything evaluates as community tier / flags OFF.

## Usage

```rust
use penguin_licensing::{LicenseClient, LicenseConfig, Tier};

let cfg = LicenseConfig::from_env("skauswatch")?
    .with_bypass_domain("skauswatch.app")
    // From the service's own canonical serving host — never an env passthrough.
    .with_deployment_domain(config.canonical_host());
let client = LicenseClient::new(cfg)?;
let _ = client.refresh().await;      // startup validation (fail-safe)
let _bg = client.spawn_refresh();    // refresh + keepalive loop

if client.flag_enabled("skauswatch.s3-scan").await { /* feature code */ }
if client.check_feature("sso").await { /* licensed feature */ }
if client.check_tier(Tier::Enterprise).await { /* enterprise-only */ }
```

### Axum gating (feature `axum`)

Flag and licence gating are **independent** and most routes want both: the
PostHog flag controls rollout ("is this feature switched on?"), the licence
controls entitlement ("is this customer allowed it?"). Stack the layers —
the outermost runs first, so put the cheap flag check outside.

```rust
use penguin_licensing::axum::{feature_gate, flag_gate, FeatureGate, FlagGate};

let router = icebox_router
    // Innermost: licence entitlement (Professional/Enterprise feature).
    .layer(axum::middleware::from_fn_with_state(
        FeatureGate::new(client.clone(), "sso"),
        feature_gate,
    ))
    // Outermost: rollout flag / kill-switch, evaluated first.
    .layer(axum::middleware::from_fn_with_state(
        FlagGate::new(client.clone(), "skauswatch.icebox"),
        flag_gate,
    ));
```

Denials are distinguishable: `403 {"error": "feature_disabled"}` from the
flag gate, `403 {"error": "feature_not_licensed"}` from the licence gate,
`403 {"error": "tier_required"}` from `TierGate`.

Ordering contract: tenant → scope → licensing gates.

## Environment

| Var | Meaning | Default |
|-----|---------|---------|
| `LICENSE_KEY` | PenguinTech license key | unset → community |
| `LICENSE_SERVER_URL` | License server | `https://license.penguintech.io` |
| `POSTHOG_HOST` | Flag host | license server URL |
| `POSTHOG_KEY` | PostHog project key | unset → flags OFF |

That is the complete list. **Nothing that affects entitlement is
environment-driven**, by design:

| Not an env var | Set instead via | Why |
|----------------|-----------------|-----|
| `RELEASE_MODE` | — (removed) | Defaulting it off made every Enterprise feature free. |
| `DEPLOYMENT_DOMAIN` / `BASE_URL` | `with_deployment_domain()` | The bypass-domain match is the only bypass; sourcing it from the environment makes a full Enterprise bypass one line of deployment YAML. |
| offline grace window | `LicenseConfig::offline_grace` | An env-settable grace is an unbounded expiry bypass. |

Pass the deployment domain from your service's own canonical serving-host
configuration — the value it would need a rebuild to change — and never
from an environment passthrough or a request header.

## Testing

```bash
cargo test --all-features
```
