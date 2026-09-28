"""Tests for the canonical AAD builder."""

import pytest

from penguin_security.crypto.envelope.aad import build_aad


def test_build_aad_is_deterministic() -> None:
    """Same inputs always produce the same AAD bytes."""
    first = build_aad(
        tenant_id=42,
        table="hub_chat_messages",
        column="message_content",
        row_uuid="11111111-1111-1111-1111-111111111111",
        dek_version=3,
    )
    second = build_aad(
        tenant_id=42,
        table="hub_chat_messages",
        column="message_content",
        row_uuid="11111111-1111-1111-1111-111111111111",
        dek_version=3,
    )
    assert first == second


@pytest.mark.parametrize(
    "field,value_a,value_b",
    [
        ("tenant_id", 1, 2),
        ("table", "table_a", "table_b"),
        ("column", "col_a", "col_b"),
        ("row_uuid", "row-a", "row-b"),
        ("dek_version", 1, 2),
    ],
)
def test_build_aad_changes_with_any_field(field: str, value_a: object, value_b: object) -> None:
    """Changing any single component changes the resulting AAD bytes."""
    base = {
        "tenant_id": 1,
        "table": "t",
        "column": "c",
        "row_uuid": "row",
        "dek_version": 1,
    }
    a = {**base, field: value_a}
    b = {**base, field: value_b}
    assert build_aad(**a) != build_aad(**b)


def test_build_aad_length_prefixing_avoids_delimiter_ambiguity() -> None:
    """Splitting/concatenating field content across a boundary must not collide.

    Without length-prefixing, ("ab", "c") and ("a", "bc") joined with "|"
    would both produce "ab|c" and "a|bc" — different strings, so a naive
    delimiter join happens to be fine here, but a value containing the
    delimiter itself would collide. Length-prefixing removes that class of
    bug entirely regardless of field content.
    """
    aad_1 = build_aad(tenant_id="a|b", table="c", column="col", row_uuid="row", dek_version=1)
    aad_2 = build_aad(tenant_id="a", table="b|c", column="col", row_uuid="row", dek_version=1)
    assert aad_1 != aad_2


def test_build_aad_rejects_negative_dek_version() -> None:
    """A negative dek_version is always a bug, not a valid version."""
    with pytest.raises(ValueError, match="non-negative"):
        build_aad(tenant_id=1, table="t", column="c", row_uuid="row", dek_version=-1)
