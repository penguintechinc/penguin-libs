# Penguin Connectors

One Rust crate per chat/streaming platform, so a Waddles data-plane service
(`core/svc_ingest`) pulls only the transitive dependencies of the platforms
it actually uses. Every crate exposes the same shape: a `Receiver` producing
raw platform payloads, a `Sender` performing outbound calls, and a
`verify_signature` function where the platform has one. None of them touch
Valkey or Postgres — see
`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` §4.10 in the
`waddles` repo for the full design.

## Crates

| Crate | Status | Covers |
|---|---|---|
| `penguin-connector-twitch` | Implemented | IRC chat receive/send, EventSub webhook signature verification + challenge handling |
| `penguin-connector-discord` | Implemented | Gateway client (identify/heartbeat/dispatch parsing), REST message send |
| `penguin-connector-slack` | Scaffolded | Socket Mode client, `chat.postMessage` — see crate docs for the deferred surface |
| `penguin-connector-youtube` | Scaffolded | Live-chat poll, `liveChatMessages.insert` — see crate docs for the deferred surface |
| `penguin-connector-kick` | Scaffolded | Pusher chat client, webhook verification, REST send — see crate docs for the deferred surface |

## What these crates are not

No Valkey/Postgres access, no bundle execution, no fan-out/subscriber logic —
that all lives in `core/svc_ingest` itself (`penguin-spine` for the stream
writes). These crates own exactly the platform wire protocols: connecting,
parsing, authenticating outbound sends, and verifying inbound signatures.

## Building and testing

```bash
cd packages/rust-connectors
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo deny check
```
