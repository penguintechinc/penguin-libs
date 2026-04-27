"""Tests for Protocol enum."""

from __future__ import annotations

import pytest

from penguin_h3.protocol import Protocol


class TestProtocol:
    """Test Protocol enum."""

    def test_protocol_h2_value(self) -> None:
        """Test Protocol.H2 enum value."""
        assert Protocol.H2.value == "h2"

    def test_protocol_h3_value(self) -> None:
        """Test Protocol.H3 enum value."""
        assert Protocol.H3.value == "h3"

    def test_protocol_h2_str(self) -> None:
        """Test string representation of Protocol.H2."""
        assert str(Protocol.H2) == "h2"

    def test_protocol_h3_str(self) -> None:
        """Test string representation of Protocol.H3."""
        assert str(Protocol.H3) == "h3"

    def test_protocol_h2_name(self) -> None:
        """Test Protocol.H2 enum name."""
        assert Protocol.H2.name == "H2"

    def test_protocol_h3_name(self) -> None:
        """Test Protocol.H3 enum name."""
        assert Protocol.H3.name == "H3"

    def test_protocol_members(self) -> None:
        """Test that Protocol enum has expected members."""
        members = list(Protocol)
        assert len(members) == 2
        assert Protocol.H2 in members
        assert Protocol.H3 in members

    def test_protocol_equality(self) -> None:
        """Test Protocol enum equality."""
        assert Protocol.H2 == Protocol.H2
        assert Protocol.H3 == Protocol.H3
        assert Protocol.H2 != Protocol.H3

    def test_protocol_from_value(self) -> None:
        """Test creating Protocol from value."""
        assert Protocol("h2") == Protocol.H2
        assert Protocol("h3") == Protocol.H3

    def test_protocol_invalid_value(self) -> None:
        """Test that invalid value raises ValueError."""
        with pytest.raises(ValueError):
            Protocol("invalid")

    def test_protocol_iteration(self) -> None:
        """Test iterating over Protocol members."""
        protocols = {p.value for p in Protocol}
        assert protocols == {"h2", "h3"}

    def test_protocol_bool_values(self) -> None:
        """Test that all Protocol members are truthy."""
        assert bool(Protocol.H2) is True
        assert bool(Protocol.H3) is True
