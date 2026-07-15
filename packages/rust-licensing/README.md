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
- **Fail-safe**: server unreachable → last cached snapshot; nothing cached →
  community tier, flags OFF. Gating reads never error and never panic.
- **Domain bypass**: deployments on `*.penguincloud.io`,
  `*.penguintech.cloud` (plus product domains added via
  `with_bypass_domain`) — or dev builds with `RELEASE_MODE` unset — evaluate
  everything as enabled. Bypass is domain-based only; no env-var kill switch.
- **Keepalive**: `POST /api/v2/keepalive` with the server-assigned id,
  driven by the background refresh loop.

## Usage

```rust
use penguin_licensing::{LicenseClient, LicenseConfig, Tier};

let cfg = LicenseConfig::from_env("skauswatch")?
    .with_bypass_domain("skauswatch.app");
let client = LicenseClient::new(cfg)?;
let _ = client.refresh().await;      // startup validation (fail-safe)
let _bg = client.spawn_refresh();    // refresh + keepalive loop

if client.flag_enabled("skauswatch.s3-scan").await { /* feature code */ }
if client.check_feature("sso").await { /* licensed feature */ }
if client.check_tier(Tier::Enterprise).await { /* enterprise-only */ }
```

### Axum gating (feature `axum`)

```rust
use penguin_licensing::axum::{flag_gate, FlagGate};

let router = icebox_router.layer(axum::middleware::from_fn_with_state(
    FlagGate::new(client.clone(), "skauswatch.icebox"),
    flag_gate,
));
```

Ordering contract: tenant → scope → licensing gates.

## Environment

| Var | Meaning | Default |
|-----|---------|---------|
| `LICENSE_KEY` | PenguinTech license key | unset → community |
| `LICENSE_SERVER_URL` | License server | `https://license.penguintech.io` |
| `POSTHOG_HOST` | Flag host | license server URL |
| `POSTHOG_KEY` | PostHog project key | unset → flags OFF |
| `RELEASE_MODE` | `true` enables enforcement | `false` (dev bypass) |
| `DEPLOYMENT_DOMAIN` / `BASE_URL` | Domain-bypass input | unset |

## Testing

```bash
cargo test --all-features
```
