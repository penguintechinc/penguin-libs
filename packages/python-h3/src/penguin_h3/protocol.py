"""Protocol detection and tracking."""

from __future__ import annotations

import enum


class Protocol(enum.Enum):
    """Supported transport protocols."""

    H2 = "h2"
    H3 = "h3"

    def __str__(self) -> str:
        return self.value
