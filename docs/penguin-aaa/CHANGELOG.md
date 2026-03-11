# penguin-aaa Changelog

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
