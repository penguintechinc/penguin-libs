"""Rate limiting utilities."""

import threading
import time

# Global in-memory rate limit store with thread safety
_rate_limit_store: dict[str, list[float]] = {}
_rate_limit_lock = threading.Lock()


def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """
    Check if a request is within rate limit.

    Uses an in-memory sliding window counter. Tracks timestamps of requests
    and enforces the limit within the given time window.

    Args:
        key: Identifier for rate limiting (e.g., user ID, IP address)
        limit: Maximum number of requests allowed in the window
        window: Time window in seconds

    Returns:
        bool: True if request is allowed, False if rate limit exceeded

    Raises:
        ValueError: If key is empty or limit is negative
    """
    if not key:
        raise ValueError("Rate limit key cannot be empty")
    if limit < 0:
        raise ValueError("Rate limit cannot be negative")

    if limit == 0:
        return False

    now = time.time()
    window_start = now - window

    with _rate_limit_lock:
        # Get existing timestamps for this key
        if key not in _rate_limit_store:
            _rate_limit_store[key] = []

        timestamps = _rate_limit_store[key]

        # Remove timestamps outside the window
        timestamps[:] = [ts for ts in timestamps if ts > window_start]

        # Check if we're within the limit
        if len(timestamps) < limit:
            # Request allowed, record this timestamp
            timestamps.append(now)
            return True
        else:
            # Rate limit exceeded
            return False
