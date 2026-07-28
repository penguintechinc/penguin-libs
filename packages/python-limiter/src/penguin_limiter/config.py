"""Rate limit configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True, frozen=True)
class RateLimitConfig:
    """Rate limit configuration."""

    rate: int
    unit: Literal["second", "minute", "hour", "day"]

    @classmethod
    def from_string(cls, config_string: str) -> RateLimitConfig:
        """Parse rate limit config from string format.

        Args:
            config_string: String in format "N/unit" e.g. "100/hour", "10/minute"

        Returns:
            RateLimitConfig instance

        Raises:
            ValueError: If format is invalid or unit is unknown
        """
        parts = config_string.strip().split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid rate limit format: {config_string!r}, expected 'N/unit'"
            )

        try:
            rate = int(parts[0].strip())
        except ValueError as e:
            raise ValueError(f"Invalid rate value: {parts[0]!r}") from e

        unit = parts[1].strip().lower()
        valid_units = ("second", "minute", "hour", "day")
        if unit not in valid_units:
            raise ValueError(
                f"Invalid unit: {unit!r}, must be one of {valid_units}"
            )

        return cls(rate=rate, unit=unit)

    def to_seconds(self) -> int:
        """Convert rate limit window to seconds."""
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        return multipliers[self.unit]
