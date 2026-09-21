//! Scope, stage identity, and Valkey key builders for the Waddles spine.
//!
//! `waddles:t:{tenant}:c:{community|_tenant}` is the shared prefix every
//! spine key uses (spec §6.2); `community: None` always renders as the
//! literal `_tenant` segment so splitting any key on `:` yields the same
//! field count regardless of activation scope (spec §5.10).

/// The literal segment rendered for a tenant-wide (non-community-scoped)
/// activation, per spec §5.10 — `community: None` is never omitted.
pub const TENANT_WIDE_SEGMENT: &str = "_tenant";

/// A (tenant, community) pair identifying the Valkey key namespace an
/// envelope or stream belongs to. `community: None` denotes a tenant-wide
/// activation and always renders as [`TENANT_WIDE_SEGMENT`] in keys.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Scope {
    /// The deployment's tenant slug (`RUNNER_TENANT_SLUG`).
    pub tenant: String,
    /// The community slug, or `None` for a tenant-wide activation.
    pub community: Option<String>,
}

impl Scope {
    /// Builds a scope from a tenant slug and an optional community slug.
    pub fn new(tenant: impl Into<String>, community: Option<String>) -> Self {
        Self {
            tenant: tenant.into(),
            community,
        }
    }

    fn community_segment(&self) -> &str {
        self.community.as_deref().unwrap_or(TENANT_WIDE_SEGMENT)
    }

    fn base(&self) -> String {
        format!("waddles:t:{}:c:{}", self.tenant, self.community_segment())
    }

    /// The per-ingest-source event stream key (spec §5.1):
    /// `{scope}:src:{platform}:{source_id}:events`.
    pub fn source_stream(&self, platform: &str, source_id: &str) -> String {
        format!("{}:src:{}:{}:events", self.base(), platform, source_id)
    }

    /// The per-bundle action stream key (spec §5.9): `{scope}:app:{app_id}:action`.
    pub fn action_stream(&self, app_id: &str) -> String {
        format!("{}:app:{}:action", self.base(), app_id)
    }

    /// The per-bundle config cache key (spec §6.2): `{scope}:app:{app_id}:cfg`.
    pub fn config_key(&self, app_id: &str) -> String {
        format!("{}:app:{}:cfg", self.base(), app_id)
    }

    /// The per-bundle state hash key (spec §6.2): `{scope}:app:{app_id}:state`.
    pub fn state_key(&self, app_id: &str) -> String {
        format!("{}:app:{}:state", self.base(), app_id)
    }
}

/// Which of the two stream-consuming stages a [`crate::SpineClient`]/
/// [`crate::GroupReader`] belongs to. Ingest only ever writes (via
/// [`Scope::source_stream`] + `SpineClient::append`) and never consumes, so
/// it has no variant here (spec §5.2, §5.9).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// `svc-process`: reads granted ingest-source streams.
    Process,
    /// `svc-action`: reads its own per-bundle action stream.
    Action,
}

impl Stage {
    /// The lowercase wire/key form (`"process"`/`"action"`), used to build
    /// the `waddles:dlq:{stage}` key and the `StageEnvelope.stage` field.
    pub fn as_str(&self) -> &'static str {
        match self {
            Stage::Process => "process",
            Stage::Action => "action",
        }
    }

    /// Parses a `StageEnvelope.stage` string into a `Stage`. Only
    /// `"process"`/`"action"` are accepted — `"ingest"` is a valid envelope
    /// stage but never reaches this crate's DLQ path (ingest never
    /// consumes), so it is deliberately rejected here rather than modeled.
    pub fn parse(s: &str) -> Result<Self, crate::SpineError> {
        match s {
            "process" => Ok(Stage::Process),
            "action" => Ok(Stage::Action),
            other => Err(crate::SpineError::Config(format!(
                "unsupported stage for spine DLQ routing: {other:?} (expected \"process\" or \"action\")"
            ))),
        }
    }
}

impl std::fmt::Display for Stage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// The dead-letter stream key for one stage (spec §5.5): `waddles:dlq:{stage}`.
/// Not yet called in-crate — wired up by `SpineClient::dead_letter` (Task 15).
#[allow(dead_code)]
pub fn dlq_key(stage: Stage) -> String {
    format!("waddles:dlq:{}", stage.as_str())
}

/// Recovers `(tenant, community)` from any well-formed spine key of the
/// shape `waddles:t:{tenant}:c:{community}:...`, returning `None` if the
/// key does not start with that prefix. Used when an entry's envelope JSON
/// fails to parse (spec §5.5 `envelope_invalid`): tenant/community for the
/// resulting DLQ record must still come from the key, never from the
/// unparsed payload (spec §3.3, §11.8).
pub fn parse_scope_from_key(key: &str) -> Option<(String, Option<String>)> {
    let rest = key.strip_prefix("waddles:t:")?;
    let (tenant, rest) = rest.split_once(":c:")?;
    let community_segment = rest.split(':').next()?;
    if tenant.is_empty() || community_segment.is_empty() {
        return None;
    }
    let community = if community_segment == TENANT_WIDE_SEGMENT {
        None
    } else {
        Some(community_segment.to_string())
    };
    Some((tenant.to_string(), community))
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case("acme", Some("main".to_string()), "twitch", "tw-channelA",
        "waddles:t:acme:c:main:src:twitch:tw-channelA:events")]
    #[case(
        "acme",
        None,
        "twitch",
        "tw-channelA",
        "waddles:t:acme:c:_tenant:src:twitch:tw-channelA:events"
    )]
    #[case("global", Some("forums".to_string()), "discord", "dg-guildX",
        "waddles:t:global:c:forums:src:discord:dg-guildX:events")]
    fn source_stream_matches_spec_shape(
        #[case] tenant: &str,
        #[case] community: Option<String>,
        #[case] platform: &str,
        #[case] source_id: &str,
        #[case] expected: &str,
    ) {
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.source_stream(platform, source_id), expected);
    }

    #[rstest]
    #[case("acme", Some("main".to_string()), "waddles.bot.commands.default",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:action",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:cfg",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:state")]
    #[case(
        "global",
        None,
        "waddles.bot.commands.default",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:action",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:cfg",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:state"
    )]
    fn app_keys_match_spec_shape(
        #[case] tenant: &str,
        #[case] community: Option<String>,
        #[case] app_id: &str,
        #[case] expected_action: &str,
        #[case] expected_cfg: &str,
        #[case] expected_state: &str,
    ) {
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.action_stream(app_id), expected_action);
        assert_eq!(scope.config_key(app_id), expected_cfg);
        assert_eq!(scope.state_key(app_id), expected_state);
    }

    #[test]
    fn stage_round_trips_through_as_str_and_parse() {
        assert_eq!(Stage::parse("process").unwrap().as_str(), "process");
        assert_eq!(Stage::parse("action").unwrap().as_str(), "action");
        assert!(Stage::parse("ingest").is_err());
        assert!(Stage::parse("bogus").is_err());
    }

    #[test]
    fn dlq_key_matches_spec_shape() {
        assert_eq!(dlq_key(Stage::Process), "waddles:dlq:process");
        assert_eq!(dlq_key(Stage::Action), "waddles:dlq:action");
    }

    #[rstest]
    #[case("waddles:t:acme:c:main:src:twitch:tw-channelA:events", Some(("acme".to_string(), Some("main".to_string()))))]
    #[case("waddles:t:global:c:_tenant:app:waddles.bot.commands.default:action", Some(("global".to_string(), None)))]
    #[case("not-a-spine-key", None)]
    #[case("waddles:dlq:process", None)]
    fn parse_scope_from_key_recovers_tenant_and_community(
        #[case] key: &str,
        #[case] expected: Option<(String, Option<String>)>,
    ) {
        assert_eq!(parse_scope_from_key(key), expected);
    }
}
