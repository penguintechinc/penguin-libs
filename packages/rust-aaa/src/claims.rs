//! Shared JWT claim set validated/issued by every ES256 consumer.

use serde::{Deserialize, Serialize};

/// Standard validated claims shared by every ES256 consumer of this crate
/// — unifies `node-agent`'s `MachineJwtClaims`
/// (`sub`/`aud`/`iss`/`iat`/`exp`/`scope`) and `testserver-rs`'s inline
/// verify-only `Claims` (`sub`/`tenant`/`scope`/`roles`/`exp`). Mirrors the
/// platform's mandatory claim set (security.md JWT Claims:
/// `sub`/`iss`/`aud`/`iat`/`exp`/`scope`/`tenant`/`teams`/`roles`).
///
/// `sub`/`iss`/`aud`/`iat`/`exp`/`scope` are structurally required — a
/// token missing any of them fails to deserialize, and so fails
/// verification before [`crate::Es256Verifier`]'s own required-claim check
/// even runs. `tenant`/`teams`/`roles` default to absent/empty for
/// services (e.g. `node-agent`'s machine-to-machine enrollment tokens)
/// that don't carry them.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Claims {
    /// Subject — the authenticated principal (user ID, node ID, service
    /// identity).
    pub sub: String,
    /// Issuer — the service that signed this token.
    pub iss: String,
    /// Audience — the service this token is presented to.
    pub aud: String,
    /// Issued-at, Unix seconds.
    pub iat: i64,
    /// Expiration, Unix seconds.
    pub exp: i64,
    /// Scope string, space-delimited `resource:action` entries (see
    /// security.md OIDC Claims & Scopes) — authz decisions branch on this,
    /// never on `roles`.
    pub scope: String,
    /// Tenant identifier — absent only for machine-to-machine tokens with
    /// no tenant context.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tenant: Option<String>,
    /// Team/OU identifiers — audit/display alongside `roles`, never an
    /// authz decision input.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub teams: Vec<String>,
    /// Role bundle names — audit/display only; never branch permission
    /// checks on these (see security.md OIDC Claims & Scopes).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub roles: Vec<String>,
}

impl Claims {
    /// Builds a minimal claim set with `tenant` absent and `teams`/`roles`
    /// empty — the shape `node-agent`'s machine-to-machine tokens need.
    /// Use struct-update syntax
    /// (`Claims { tenant: Some(t), ..Claims::new(...) }`) to add the
    /// optional fields a user-facing token needs.
    #[must_use]
    pub fn new(
        sub: impl Into<String>,
        iss: impl Into<String>,
        aud: impl Into<String>,
        iat: i64,
        exp: i64,
        scope: impl Into<String>,
    ) -> Self {
        Self {
            sub: sub.into(),
            iss: iss.into(),
            aud: aud.into(),
            iat,
            exp,
            scope: scope.into(),
            tenant: None,
            teams: Vec::new(),
            roles: Vec::new(),
        }
    }
}
