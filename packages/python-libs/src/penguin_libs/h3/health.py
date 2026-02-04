"""Health check ASGI application for HTTP/3 services."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class HealthCheck:
    """Minimal ASGI app that responds to health check requests.

    Mount at /healthz or compose with your main ASGI app.

    Usage::

        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", True)
    """

    def __init__(self) -> None:
        self._statuses: dict[str, bool] = {"": True}

    def set_status(self, service: str, healthy: bool) -> None:
        """Set the health status of a named service."""
        self._statuses[service] = healthy

    def is_healthy(self, service: str = "") -> bool:
        """Check if a specific service (or overall) is healthy."""
        return self._statuses.get(service, False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return

        overall = all(self._statuses.values())
        status = 200 if overall else 503
        body = json.dumps({
            "status": "healthy" if overall else "unhealthy",
            "services": {
                k: ("ok" if v else "failing")
                for k, v in self._statuses.items()
                if k
            },
        }).encode()

        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
