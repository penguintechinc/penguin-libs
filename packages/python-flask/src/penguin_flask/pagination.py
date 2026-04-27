"""Pagination helpers for Flask APIs.

Provides ``get_pagination_params`` to extract page/per_page from request args
and ``paginate`` to paginate SQLAlchemy queries, penguin-dal Rows, or plain lists.
"""

from __future__ import annotations

from typing import Any


def get_pagination_params(default_per_page: int = 20) -> tuple[int, int]:
    """Extract ``page`` and ``per_page`` from Flask ``request.args``.

    Validates that both values are positive integers. Falls back to defaults
    when query params are absent or invalid.

    Args:
        default_per_page: Items per page when ``per_page`` not in request args.

    Returns:
        Tuple of ``(page, per_page)`` where both are >= 1.

    Example::

        page, per_page = get_pagination_params(default_per_page=50)
    """
    try:
        from flask import request
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "penguin_libs.flask requires Flask. Install with: pip install penguin-libs[flask]"
        ) from exc

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = max(1, int(request.args.get("per_page", default_per_page)))
    except (TypeError, ValueError):
        per_page = default_per_page

    return page, per_page


def paginate(query_or_list: Any, page: int, per_page: int) -> dict[str, Any]:
    """Paginate a query, Rows object, or plain list.

    Supports three input types:

    * **SQLAlchemy Query** — detected by presence of ``.count()`` method;
      uses ``.offset().limit()`` for efficient pagination.
    * **penguin-dal Rows / list-like** — detected by ``len()``; sliced in Python.
    * **Plain Python list** — sliced directly.

    Args:
        query_or_list: Data source to paginate.
        page: 1-based page number.
        per_page: Maximum items per page.

    Returns:
        Dict with keys ``items``, ``page``, ``per_page``, ``total``, ``pages``.

    Example::

        result = paginate(db(db.users).select(), page=2, per_page=20)
        # {"items": [...], "page": 2, "per_page": 20, "total": 85, "pages": 5}
    """
    import math

    page = max(1, page)
    per_page = max(1, per_page)
    offset = (page - 1) * per_page

    # SQLAlchemy Query detection
    if hasattr(query_or_list, "count") and hasattr(query_or_list, "offset"):
        total: int = query_or_list.count()
        items = query_or_list.offset(offset).limit(per_page).all()
    else:
        # list-like (penguin-dal Rows, plain list, etc.)
        all_items = list(query_or_list)
        total = len(all_items)
        items = all_items[offset : offset + per_page]

    pages = math.ceil(total / per_page) if per_page > 0 else 0

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
    }
