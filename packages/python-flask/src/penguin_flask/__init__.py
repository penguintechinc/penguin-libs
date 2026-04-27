"""Flask utilities for penguin-libs.

Provides standardized response envelopes and pagination helpers
following the flask-backend.md API response format.

Usage::

    from penguin_flask import success_response, error_response, paginate

    @app.route("/api/v1/users")
    def list_users():
        page, per_page = get_pagination_params()
        users = db(db.users).select()
        return success_response(
            data=paginate(users, page, per_page),
        )
"""

from penguin_flask.pagination import get_pagination_params, paginate
from penguin_flask.responses import error_response, success_response

__all__ = [
    "error_response",
    "get_pagination_params",
    "paginate",
    "success_response",
]
