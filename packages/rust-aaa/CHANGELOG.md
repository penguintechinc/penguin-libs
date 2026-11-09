# Changelog

## 0.2.0

Security hardening release; contains breaking changes (pre-1.0 minor bump; `rust-aaa-v0.1.0` is tagged).

### Breaking
- `Es256Verifier::builder(..).audience(..).issuer(..).build()` replaces direct construction. Audience and issuer are mandatory; `build()` returns `AaaError::Config` if either is unset or empty.
- Algorithm is derived from the key type; tokens whose `alg` does not match are rejected. HMAC and `none` are never accepted.

### Security
- `iat` is now bounded against the current time: tokens with `iat` more than 60s in the future are rejected (previously `iat = now + 10y, exp = iat + 1h` verified).
- `exp` required, `nbf` enforced, token lifetime (`exp - iat`) capped at 24h, clock-skew leeway capped at 60s.
- Header `alg` from untrusted tokens is never echoed into error text.
- Dependency updates: `p256`/`p521` 0.14.
