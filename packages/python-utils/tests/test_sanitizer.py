"""Sanitizer test suite with shared test vectors."""

import json
import pathlib

import pytest

from penguintechinc_utils.logging import (
    SANITIZE_ERROR_PLACEHOLDER,
    SENSITIVE_PLACEHOLDER,
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
