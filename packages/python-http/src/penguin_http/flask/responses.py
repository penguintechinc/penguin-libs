"""Standardized Flask response helpers.

All responses follow the envelope format defined in flask-backend.md::

    {
        "status": "success" | "error",
        "data": {...},
        "message": "...",
        "meta": {...}
    }
"""

from __future__ import annotations

from typing import Any

try:
    from flask import jsonify
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "penguin_libs.flask requires Flask. Install with: pip install penguin-libs[flask]"
    ) from exc


def success_response(
    data: Any = None,
    message: str = "Success",
    status_code: int = 200,
    meta: dict | None = None,
):
    """Return a standardized success JSON response.

    Args:
        data: The response payload. Can be any JSON-serialisable value.
        message: Human-readable success message.
        status_code: HTTP status code (default: 200).
        meta: Optional metadata dict (e.g., pagination info).

    Returns:
        Flask Response with JSON body and given status code.

    Example::

        return success_response(data={"id": 1, "name": "Alice"}, status_code=201)
    """
    body: dict[str, Any] = {
        "status": "success",
        "data": data,
        "message": message,
    }
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status_code


def error_response(
    message: str,
    status_code: int = 400,
    **kwargs: Any,
):
    """Return a standardized error JSON response.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code (default: 400).
        **kwargs: Additional fields merged into the response body
            (e.g., ``field="email"``, ``code="INVALID_EMAIL"``).

    Returns:
        Flask Response with JSON body and given status code.

    Example::

        return error_response("Email is required", status_code=422, field="email")
    """
    body: dict[str, Any] = {
        "status": "error",
        "message": message,
        **kwargs,
    }
    return jsonify(body), status_code
