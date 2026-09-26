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
