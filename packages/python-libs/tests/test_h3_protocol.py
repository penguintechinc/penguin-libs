"""Tests for penguin_libs.h3.protocol module."""

from penguin_libs.h3.protocol import Protocol


def test_protocol_values():
    """Test Protocol enum values."""
    assert Protocol.H2.value == "h2"
    assert Protocol.H3.value == "h3"


def test_protocol_str():
    """Test Protocol enum string representation."""
    assert str(Protocol.H2) == "h2"
    assert str(Protocol.H3) == "h3"


def test_protocol_members():
    """Test that Protocol has exactly 2 members."""
    members = list(Protocol)
    assert len(members) == 2
    assert Protocol.H2 in members
    assert Protocol.H3 in members
