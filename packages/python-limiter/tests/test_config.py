"""Tests for rate-limit config and limit-string parsing."""

from __future__ import annotations

import pytest

from penguin_limiter.config import Algorithm, RateLimitConfig, parse_limit, parse_multi_tier


class TestParseLimitString:
    @pytest.mark.parametrize("spec,limit,window", [
        ("100/minute", 100, 60),
        ("10/second", 10, 1),
        ("5000/hour", 5000, 3600),
        ("1/day", 1, 86400),
        ("50/min", 50, 60),
        ("30/sec", 30, 1),
        ("200/hr", 200, 3600),
        ("  100 / minute  ", 100, 60),  # whitespace tolerance
        ("100/MINUTE", 100, 60),        # case insensitive
    ])
    def test_valid_specs(self, spec: str, limit: int, window: int) -> None:
        l, w = parse_limit(spec)
        assert l == limit
        assert w == window

    def test_invalid_spec_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid rate-limit spec"):
            parse_limit("100 per minute")

    def test_invalid_unit_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_limit("100/week")


class TestParseMultiTier:
    def test_single_tier(self) -> None:
        tiers = parse_multi_tier("100/minute")
        assert tiers == [(100, 60)]

    def test_multi_tier(self) -> None:
        tiers = parse_multi_tier("10/second;100/minute;1000/hour")
        assert tiers == [(10, 1), (100, 60), (1000, 3600)]

    def test_whitespace_around_semicolons(self) -> None:
        tiers = parse_multi_tier("10/second ; 100/minute")
        assert tiers == [(10, 1), (100, 60)]


class TestRateLimitConfig:
    def test_from_string_sets_limit_and_window(self) -> None:
        config = RateLimitConfig.from_string("100/minute")
        assert config.limit == 100
        assert config.window == 60

    def test_from_string_defaults(self) -> None:
        config = RateLimitConfig.from_string("50/second")
        assert config.algorithm == Algorithm.SLIDING_WINDOW
        assert config.skip_private_ips is True
        assert config.fail_open is True
        assert config.add_headers is True

    def test_from_string_override_skip_private_ips(self) -> None:
        config = RateLimitConfig.from_string("100/minute", skip_private_ips=False)
        assert config.skip_private_ips is False

    def test_from_string_multi_tier_stores_tiers(self) -> None:
        config = RateLimitConfig.from_string("10/second;100/minute")
        assert config.limit == 10  # tightest tier is primary
        assert config.window == 1
        assert config.tiers == [(10, 1), (100, 60)]

    def test_rate_per_second(self) -> None:
        config = RateLimitConfig(limit=120, window=60)
        assert config.rate_per_second == pytest.approx(2.0)

    def test_manual_construction(self) -> None:
        config = RateLimitConfig(limit=10, window=1, algorithm=Algorithm.TOKEN_BUCKET)
        assert config.algorithm == Algorithm.TOKEN_BUCKET
