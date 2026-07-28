"""Tests for RateLimitConfig."""

import pytest

from penguin_limiter import RateLimitConfig


class TestRateLimitConfig:
    """Test RateLimitConfig parsing and methods."""

    def test_from_string_hour(self) -> None:
        """Test parsing hour-based config."""
        config = RateLimitConfig.from_string("100/hour")
        assert config.rate == 100
        assert config.unit == "hour"
        assert config.to_seconds() == 3600

    def test_from_string_minute(self) -> None:
        """Test parsing minute-based config."""
        config = RateLimitConfig.from_string("60/minute")
        assert config.rate == 60
        assert config.unit == "minute"
        assert config.to_seconds() == 60

    def test_from_string_second(self) -> None:
        """Test parsing second-based config."""
        config = RateLimitConfig.from_string("10/second")
        assert config.rate == 10
        assert config.unit == "second"
        assert config.to_seconds() == 1

    def test_from_string_day(self) -> None:
        """Test parsing day-based config."""
        config = RateLimitConfig.from_string("1000/day")
        assert config.rate == 1000
        assert config.unit == "day"
        assert config.to_seconds() == 86400

    def test_from_string_with_whitespace(self) -> None:
        """Test parsing with extra whitespace."""
        config = RateLimitConfig.from_string("  100  /  hour  ")
        assert config.rate == 100
        assert config.unit == "hour"

    def test_from_string_invalid_format(self) -> None:
        """Test error on invalid format."""
        with pytest.raises(ValueError, match="Invalid rate limit format"):
            RateLimitConfig.from_string("100-hour")

    def test_from_string_invalid_rate(self) -> None:
        """Test error on invalid rate value."""
        with pytest.raises(ValueError, match="Invalid rate value"):
            RateLimitConfig.from_string("abc/hour")

    def test_from_string_invalid_unit(self) -> None:
        """Test error on invalid unit."""
        with pytest.raises(ValueError, match="Invalid unit"):
            RateLimitConfig.from_string("100/week")

    def test_direct_construction(self) -> None:
        """Test direct construction."""
        config = RateLimitConfig(rate=50, unit="minute")
        assert config.rate == 50
        assert config.unit == "minute"
        assert config.to_seconds() == 60

    def test_frozen(self) -> None:
        """Test that config is immutable."""
        config = RateLimitConfig(rate=100, unit="hour")
        with pytest.raises(AttributeError):
            config.rate = 200  # type: ignore
