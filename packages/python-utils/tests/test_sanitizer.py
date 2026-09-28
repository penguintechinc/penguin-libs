"""Sanitizer test suite with shared test vectors."""

import json
import pathlib

import pytest

from penguintechinc_utils.logging import (
    SANITIZE_ERROR_PLACEHOLDER,
    is_sensitive_key,
    redact_text,
    sanitize_log_data,
)

VECTORS = json.loads(
    (pathlib.Path(__file__).parent / "vectors" / "sanitizer_vectors.json").read_text()
)


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_shared_vectors(case: dict) -> None:
    """Test against shared vector file (cross-language contract)."""
    assert sanitize_log_data(case["input"]) == case["expected"]


def test_key_match_is_not_naive_substring() -> None:
    """Word-boundary matching: 'otp' in 'footprint' must NOT redact."""
    # "footprint" contains "otp" but must NOT be treated as sensitive
    assert is_sensitive_key("footprint") is False
    assert is_sensitive_key("otp") is True
    assert is_sensitive_key("mfa_code") is True


def test_email_redacted_mid_string() -> None:
    """Emails must be redacted anywhere in a string."""
    assert "alice@example.com" not in redact_text("user alice@example.com logged in")


def test_list_values_are_scanned() -> None:
    """List elements must be scanned for emails and sensitive data."""
    out = sanitize_log_data({"items": ["ok", "bob@example.com"]})
    assert "bob@example.com" not in json.dumps(out)


def test_fail_closed_on_hostile_repr() -> None:
    """If sanitizing a value raises, use SANITIZE_ERROR_PLACEHOLDER."""

    class Boom:
        def __repr__(self) -> str:
            raise RuntimeError("nope")

    out = sanitize_log_data({"x": Boom()})
    assert out["x"] == SANITIZE_ERROR_PLACEHOLDER


def test_prefixed_suffixed_compound_keys() -> None:
    """Compound keys with prefixes/suffixes must match as contiguous segments."""
    # Prefixed compound keys: vendor_api_key should match api_key
    assert is_sensitive_key("stripe_api_key") is True
    assert is_sensitive_key("aws_api_key") is True
    assert is_sensitive_key("user_session_id") is True
    assert is_sensitive_key("access_token_expiry") is True

    # Single-segment variations must NOT match
    assert is_sensitive_key("footprint") is False  # contains "otp" but single segment
    assert is_sensitive_key("tokenizer") is False  # contains "token" but single segment


def test_redacts_sensitive_query_param_value() -> None:
    """Sensitive query-parameter values (e.g. token=) are redacted; emails still redacted."""
    out = redact_text("GET https://api.example.com/v1/x?token=sk-live-abc123&user=eve@example.com")
    assert "sk-live-abc123" not in out  # token value redacted
    assert "eve@example.com" not in out  # email still redacted
    assert "token=[REDACTED]" in out  # replaced, not dropped


def test_non_sensitive_query_param_survives() -> None:
    """Benign query params (page, sort) must survive untouched."""
    out = redact_text("https://x/y?page=2&sort=name")
    assert out == "https://x/y?page=2&sort=name"  # benign params untouched


def test_sanitize_recurses_into_tuple_and_set() -> None:
    """tuple and set values are recursed into (as list) just like list."""
    out_tuple = sanitize_log_data({"t": ("ok", "eve@example.com")})
    assert "eve@example.com" not in json.dumps(out_tuple)
    assert isinstance(out_tuple["t"], list)

    out_set = sanitize_log_data({"s": {"ok", "eve@example.com"}})
    assert "eve@example.com" not in json.dumps(out_set)
    assert isinstance(out_set["s"], list)


def test_query_param_value_stops_at_ampersand() -> None:
    """A sensitive query-param value stops at & so a sibling param survives."""
    out = redact_text("?token=sk-live-abc123&user=bob")
    assert "sk-live-abc123" not in out
    assert "token=[REDACTED]" in out
    assert "bob" in out
    assert "user" in out


def test_url_scheme_is_not_swallowed_as_a_value() -> None:
    """The 'https:' prefix must not be treated as key/value; only api_key's value goes."""
    out = redact_text("https://api.x/v1?api_key=sk-LIVE-1")
    assert "sk-LIVE-1" not in out
    assert out == "https://api.x/v1?api_key=[REDACTED]"


def test_header_style_bearer_token_fully_redacted() -> None:
    """GAP 1: a space-containing 'Authorization: Bearer <token>' value must be fully gone."""
    out = redact_text("Authorization: Bearer abc123")
    assert "abc123" not in out


def test_bare_keyvalue_in_free_text_redacted() -> None:
    """GAP 2: a bare 'password=' pair in free text (no ?/&/# anchor) must be redacted."""
    out = redact_text("note: password=hunter2 error")
    assert "hunter2" not in out
    assert "error" in out


def test_benign_substring_keys_survive_in_kv_form() -> None:
    """Keys is_sensitive_key already treats as benign must stay unredacted in kv form too."""
    assert redact_text("tokenizer=gpt2") == "tokenizer=gpt2"
    assert redact_text("authorized=true") == "authorized=true"


def test_benign_params_and_time_format_survive() -> None:
    """Benign query params and a bare HH:MM time value must not be mistaken for kv secrets."""
    assert redact_text("?page=2&sort=name") == "?page=2&sort=name"
    assert redact_text("time=12:30") == "time=12:30"


def test_base64_padded_value_fully_redacted() -> None:
    """A base64-encoded secret (incl. '==' padding) must redact in full, not truncate at '='."""
    assert redact_text("token=YWJjMTIz==") == "token=[REDACTED]"


def test_base64_padded_query_param_value_fully_redacted() -> None:
    """Same as above, in query-string form, with a sibling benign param surviving."""
    out = redact_text("?api_key=c2VjcmV0==&x=1")
    assert "c2VjcmV0" not in out
    assert out == "?api_key=[REDACTED]&x=1"


def test_base64_padded_secret_key_fully_redacted() -> None:
    """A bare 'secret=' with base64 padding at end-of-string is fully redacted."""
    assert redact_text("secret=abcdef==") == "secret=[REDACTED]"


def test_value_with_embedded_equals_not_partially_redacted() -> None:
    """An '=' appearing mid-value (not just trailing padding) must not truncate the redaction."""
    out = redact_text("password=P@ss==word")
    assert "P@ss==word" not in out
    assert out == "password=[REDACTED]"


def test_standard_base64_alphabet_chars_fully_redacted() -> None:
    """Standard base64 chars '/' and '+' inside a value must not stop redaction early."""
    assert redact_text("token=ab/cd+ef==") == "token=[REDACTED]"


def test_base64_value_after_non_sensitive_label_fully_redacted() -> None:
    """A base64 secret must redact in full even when preceded by a non-sensitive 'label: '."""
    out = redact_text("note: token=YWJjMTIz== error")
    assert "YWJjMTIz" not in out
    assert out == "note: token=[REDACTED] error"


def test_colon_space_base64_value_fully_redacted() -> None:
    """A colon-space secret whose value contains '=' must redact in full, not leak.

    Regression: the colon-space branch of _KV carried a negative lookahead that
    refused to match when the value looked like a fresh 'key=' pair, so an
    '='-containing (e.g. base64-padded) value was not redacted at all.
    """
    assert redact_text("token: YWJjMTIz==") == "token: [REDACTED]"
    assert redact_text("secret: abcdef==") == "secret: [REDACTED]"


# The handoff invariant table, as an executable gate. Every row must hold
# together; the no-over-redaction rows are as load-bearing as the redaction rows.
_MUST_REDACT = [
    ("token: YWJjMTIz==", "YWJjMTIz"),
    ("secret: abcdef==", "abcdef"),
    ("token=YWJjMTIz==", "YWJjMTIz"),
    ("?api_key=c2VjcmV0==&x=1", "c2VjcmV0"),
    ("password=P@ss==word", "P@ss==word"),
    ("token=ab/cd+ef==", "ab/cd+ef"),
    ("?token=sk-live-abc123&user=bob", "sk-live-abc123"),
    ("https://api.x/v1?api_key=sk-LIVE-1", "sk-LIVE-1"),
    ("Authorization: Bearer abc123", "abc123"),
    ("note: password=hunter2 error", "hunter2"),
]

_MUST_NOT_CHANGE = [
    "tokenizer=gpt2",
    "authorized=true",
    "?page=2&sort=name",
    "time=12:30",
]


@pytest.mark.parametrize("text,secret", _MUST_REDACT, ids=[t for t, _ in _MUST_REDACT])
def test_invariant_secret_never_survives(text: str, secret: str) -> None:
    """Every invariant-table secret must be absent from the redacted output."""
    assert secret not in redact_text(text)


@pytest.mark.parametrize("text", _MUST_NOT_CHANGE)
def test_invariant_benign_text_unchanged(text: str) -> None:
    """Benign key/value text must pass through byte-identical (no over-redaction)."""
    assert redact_text(text) == text


def test_invariant_non_secret_neighbours_survive() -> None:
    """Redacting a secret must not take its non-sensitive neighbours with it."""
    assert "user=bob" in redact_text("?token=sk-live-abc123&user=bob")
    assert "error" in redact_text("note: password=hunter2 error")
    assert redact_text("https://api.x/v1?api_key=sk-LIVE-1").startswith("https://api.x/v1?")


def test_invariant_emails_redacted_anywhere() -> None:
    """Emails are redacted wherever they appear, including beside a secret."""
    out = redact_text("?token=sk-1&user=eve@example.com")
    assert "eve@example.com" not in out
    assert "[email]" in out


def test_walrus_style_separator_does_not_leak() -> None:
    """A two-character separator ('key := value') must not leave the value exposed.

    Regression: a single-char separator class consumed only ':', so '=' became the
    whole value and the real secret fell outside the match entirely.
    """
    out = redact_text("token := sk-live-abc123")
    assert "sk-live-abc123" not in out
    assert out == "token := [REDACTED]"


def test_separator_may_span_a_line_break() -> None:
    """A secret on the line after its key must still be redacted."""
    out = redact_text("token:\nsk-live-abc123")
    assert "sk-live-abc123" not in out


def test_quoted_json_key_is_recognised() -> None:
    """A JSON/repr-quoted sensitive key must be redacted, and the structure kept.

    Services routinely log f"payload: {json.dumps(data)}", so the quoted form is
    as common as the bare one.
    """
    out = redact_text('{"token": "sk-live-abc123"}')
    assert "sk-live-abc123" not in out
    assert out == '{"token": "[REDACTED]"}'

    out = redact_text("{'api_key': 'sk-LIVE-2'}")
    assert "sk-LIVE-2" not in out
    assert out == "{'api_key': '[REDACTED]'}"


def test_quoted_benign_json_keys_survive() -> None:
    """Benign quoted keys must pass through byte-identical."""
    assert redact_text('{"page": "2", "sort": "name"}') == '{"page": "2", "sort": "name"}'


def test_deeply_chained_pairs_do_not_exhaust_the_stack() -> None:
    """A long chain of key=key=...=secret must redact, never raise RecursionError.

    Rescanning a benign key's value is done by advancing a scan position, not by
    recursive descent, so chain length costs time and not stack frames.
    """
    text = "=".join(["k"] * 3000) + "=token=sk-live-DEEP"
    out = redact_text(text)
    assert "sk-live-DEEP" not in out
    assert "[REDACTED]" in out


def test_long_word_run_is_not_pathological() -> None:
    """Scanning a long separator-free string must stay fast (no quadratic blowup)."""
    import time

    text = "a" * 40000
    start = time.perf_counter()
    assert redact_text(text) == text
    assert time.perf_counter() - start < 1.0


def test_doubled_and_escaped_quotes_do_not_hide_a_secret() -> None:
    """Quote noise around a value must not stop the value being redacted.

    A value class that excluded quotes let 'token=""x""' and an escaped
    '{"token": "\\"x\\""}' through untouched.
    """
    assert "secretvalue" not in redact_text('token=""secretvalue""')
    assert "secretvalue" not in redact_text('{"token": "\\"secretvalue\\""}')


def test_redaction_is_idempotent() -> None:
    """Re-redacting already-redacted text must be a no-op.

    The placeholder ends in ']', a character the value scan trims as structural,
    so a naive second pass chipped it off and appended another.
    """
    once = redact_text('{"token": "sk-live-abc", "note": "ok"}')
    assert redact_text(once) == once
    assert redact_text("token=[REDACTED]") == "token=[REDACTED]"
    assert redact_text(redact_text("token=abc")) == "token=[REDACTED]"


def test_json_stays_parseable_after_redaction() -> None:
    """Redacting a value inside JSON must leave the document parseable."""
    out = redact_text('{"token": "sk-live-abc", "page": "2"}')
    assert "sk-live-abc" not in out
    parsed = json.loads(out)
    assert parsed["token"] == "[REDACTED]"
    assert parsed["page"] == "2"


def test_email_adjacent_to_another_email_still_redacted() -> None:
    """Two addresses with no separator between them must BOTH be redacted.

    A lookbehind-based scan optimisation refused the second one, because a
    lookbehind tests the raw string rather than what a prior match consumed.
    """
    out = redact_text("a@b.coma.b@x.co")
    assert "@" not in out
    assert out == "[email][email]"


def test_yaml_block_scalar_is_a_documented_limitation() -> None:
    """A YAML block scalar's indented lines are NOT redacted -- known limitation.

    redact_text is a single-line key/value scanner; a multi-line block body is out
    of its reach. Asserted so the gap is explicit rather than silently assumed
    covered, and so it fails loudly if the behaviour ever changes.
    """
    out = redact_text("token: |\n  line1secret\n  line2secret")
    assert out.startswith("token: [REDACTED]")
    assert "line1secret" in out  # documents the gap; do not log YAML blocks raw


@pytest.mark.parametrize("unit", ["k=", "k:", 'k="v" ', "a@"])
def test_scan_cost_stays_near_linear(unit: str) -> None:
    """Scanning must not blow up super-linearly on repeated key/value shapes.

    A ratio bound rather than a wall-clock bound, so the gate means the same thing
    on a fast laptop and a loaded CI box. Chained 'k=' pairs are the shape that
    previously went quadratic (7.8s at 80KB), and a wall-clock-only gate on a
    separator-free string never exercised it.
    """
    import time

    def elapsed(n: int) -> float:
        text = (unit * ((n // len(unit)) + 1))[:n]
        start = time.perf_counter()
        redact_text(text)
        return time.perf_counter() - start

    elapsed(10_000)  # warm up, so first-call costs do not skew the ratio
    small = elapsed(10_000)
    large = elapsed(80_000)
    # An 8x input increase costs ~8x if linear and ~64x if quadratic, so the two are
    # far enough apart that a 24x bound tolerates timer noise and the uneven overhead
    # of running under coverage while still failing hard on n^2.
    assert large < max(small * 24.0, 0.05), f"{unit!r}: 10k={small:.4f}s 80k={large:.4f}s"


def test_separator_with_no_key_in_front_is_left_alone() -> None:
    """A ':' or '=' with no key before it must pass through untouched."""
    assert redact_text("://x") == "://x"
    assert redact_text("http://host:8080/path") == "http://host:8080/path"
    assert redact_text("::==::") == "::==::"


def test_sensitive_key_with_no_value_is_left_alone() -> None:
    """A sensitive key with nothing after the separator must not invent a value."""
    assert redact_text("token=") == "token="
    assert redact_text("password:") == "password:"
    assert redact_text("secret= ") == "secret= "


def test_structured_field_and_free_text_agree_on_sensitivity() -> None:
    """The dict path and the text path must make the SAME key judgement.

    One source of truth (is_sensitive_key) is the point; a second word list is how
    two paths drift apart.
    """
    for name in ("stripe_api_key", "authorization", "session_id", "mfa_code"):
        assert sanitize_log_data({name: "v"})[name] == "[REDACTED]"
        assert "v" not in redact_text(name + "=v")
    for benign in ("tokenizer", "footprint", "page", "authorized"):
        assert sanitize_log_data({benign: "v"})[benign] == "v"
        assert redact_text(benign + "=v") == benign + "=v"
