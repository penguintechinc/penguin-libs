"""ASGI test helpers and fixtures for PenguinTech middleware tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def asgi_http_scope(
    path: str = "/api",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    """Return a minimal ASGI HTTP scope dict for testing middleware.

    Args:
        path: Request path (default: "/api").
        method: HTTP method (default: "GET").
        headers: List of (name, value) byte tuples (default: empty list).

    Returns:
        A dict suitable for passing as the ``scope`` argument to ASGI apps.
    """
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "state": {},
    }


def asgi_send_collector() -> tuple[list[dict[str, Any]], Callable[..., Any]]:
    """Return a (messages list, async send callable) pair.

    Use the returned ``send`` callable as the ASGI send argument.  After the
    middleware or app has run, inspect ``messages`` to assert on response
    status codes and bodies.

    Returns:
        A 2-tuple of ``(messages, send)`` where *messages* is a mutable list
        that the send callable appends to, and *send* is an ``async def``
        callable accepting a single message dict.
    """
    messages: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        messages.append(msg)

    return messages, send


def asgi_ok_app(status: int = 200) -> Any:
    """Return a minimal ASGI app that always responds with *status*.

    Args:
        status: HTTP status code to return (default: 200).

    Returns:
        An async ASGI callable ``(scope, receive, send) -> None``.
    """

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return _app
