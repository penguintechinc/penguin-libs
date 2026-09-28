# penguin-aaa Changelog

## 0.3.0

- Folded the `penguin-sal` secrets-management library (packages/python-secrets)
  in as `penguin_aaa.secrets` — same public API, new import path and new
  `[secrets]` / `[secrets-<backend>]` optional extras (vault, aws, gcp, azure,
  oci, k8s, onepassword, passbolt, doppler, infisical, cyberark)
- Base `penguin-aaa` install gains no new dependencies; a missing backend SDK
  raises `AdapterNotInstalledError` naming the exact extra to install
- `penguin-secrets` / `penguin-sal` is superseded and no longer published —
  migrate imports from `penguin_sal.X` to `penguin_aaa.secrets.X`

## 0.1.0

- Initial release
- OIDC Provider: issue and revoke JWTs with OIDC claim set (`sub`, `iss`, `aud`, `scope`, `tenant`, `teams`, `roles`)
- OIDC Relying Party: validate incoming JWTs, exchange auth codes, refresh tokens
- `Claims` and `TokenSet` dataclasses
- Key stores: `MemoryKeyStore`, `FileKeyStore`
- RBAC middleware: `require_scope` decorator for Flask, `AuthMiddleware` for ASGI
- Tenant isolation enforcement
- Audit logging for authentication events
- Cryptographic hardening utilities
