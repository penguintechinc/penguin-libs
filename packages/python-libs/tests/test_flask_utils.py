"""Tests for penguin_libs.flask response helpers and pagination."""

import pytest

try:
    from flask import Flask

    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

pytestmark = pytest.mark.skipif(not HAS_FLASK, reason="Flask not installed")


@pytest.fixture
def app():
    """Minimal Flask app for testing."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSuccessResponse:
    def test_default_response(self, app):
        """success_response returns 200 with success status and data."""
        from penguin_libs.flask import success_response

        with app.app_context():
            response, status = success_response(data={"id": 1})
            assert status == 200
            body = response.get_json()
            assert body["status"] == "success"
            assert body["data"] == {"id": 1}
            assert body["message"] == "Success"

    def test_custom_message_and_status(self, app):
        """success_response respects custom message and status_code."""
        from penguin_libs.flask import success_response

        with app.app_context():
            response, status = success_response(
                data={"id": 2},
                message="Created",
                status_code=201,
            )
            assert status == 201
            body = response.get_json()
            assert body["message"] == "Created"

    def test_with_meta(self, app):
        """success_response includes meta when provided."""
        from penguin_libs.flask import success_response

        meta = {"page": 1, "total": 100}
        with app.app_context():
            response, status = success_response(data=[], meta=meta)
            body = response.get_json()
            assert body["meta"] == meta

    def test_no_meta_key_when_none(self, app):
        """success_response omits meta key when meta=None."""
        from penguin_libs.flask import success_response

        with app.app_context():
            response, _ = success_response(data={})
            body = response.get_json()
            assert "meta" not in body

    def test_none_data(self, app):
        """success_response handles None data."""
        from penguin_libs.flask import success_response

        with app.app_context():
            response, status = success_response()
            body = response.get_json()
            assert body["data"] is None
            assert status == 200


class TestErrorResponse:
    def test_default_400(self, app):
        """error_response returns 400 with error status."""
        from penguin_libs.flask import error_response

        with app.app_context():
            response, status = error_response("Something went wrong")
            assert status == 400
            body = response.get_json()
            assert body["status"] == "error"
            assert body["message"] == "Something went wrong"

    def test_custom_status_code(self, app):
        """error_response uses custom status_code."""
        from penguin_libs.flask import error_response

        with app.app_context():
            _, status = error_response("Not found", status_code=404)
            assert status == 404

    def test_extra_kwargs_included(self, app):
        """error_response merges extra kwargs into body."""
        from penguin_libs.flask import error_response

        with app.app_context():
            response, _ = error_response(
                "Validation error",
                status_code=422,
                field="email",
                code="INVALID_EMAIL",
            )
            body = response.get_json()
            assert body["field"] == "email"
            assert body["code"] == "INVALID_EMAIL"


class TestGetPaginationParams:
    def test_defaults_when_no_args(self, app):
        """Returns page=1, per_page=20 when no query params."""
        from penguin_libs.flask import get_pagination_params

        with app.test_request_context("/"):
            page, per_page = get_pagination_params()
            assert page == 1
            assert per_page == 20

    def test_custom_default_per_page(self, app):
        """Respects default_per_page argument."""
        from penguin_libs.flask import get_pagination_params

        with app.test_request_context("/"):
            _, per_page = get_pagination_params(default_per_page=50)
            assert per_page == 50

    def test_reads_from_request_args(self, app):
        """Extracts page and per_page from request args."""
        from penguin_libs.flask import get_pagination_params

        with app.test_request_context("/?page=3&per_page=10"):
            page, per_page = get_pagination_params()
            assert page == 3
            assert per_page == 10

    def test_negative_page_clamps_to_1(self, app):
        """Negative page value clamped to 1."""
        from penguin_libs.flask import get_pagination_params

        with app.test_request_context("/?page=-5"):
            page, _ = get_pagination_params()
            assert page == 1

    def test_invalid_page_defaults_to_1(self, app):
        """Non-integer page value defaults to 1."""
        from penguin_libs.flask import get_pagination_params

        with app.test_request_context("/?page=abc"):
            page, _ = get_pagination_params()
            assert page == 1


class TestPaginate:
    def test_plain_list_first_page(self, app):
        """Paginates plain list, first page."""
        from penguin_libs.flask import paginate

        items = list(range(100))
        result = paginate(items, page=1, per_page=20)
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["total"] == 100
        assert result["pages"] == 5
        assert result["items"] == list(range(20))

    def test_plain_list_last_page(self, app):
        """Paginates plain list, last partial page."""
        from penguin_libs.flask import paginate

        items = list(range(25))
        result = paginate(items, page=2, per_page=20)
        assert result["items"] == list(range(20, 25))
        assert result["total"] == 25
        assert result["pages"] == 2

    def test_empty_list(self, app):
        """Empty list returns zero total and pages."""
        from penguin_libs.flask import paginate

        result = paginate([], page=1, per_page=20)
        assert result["total"] == 0
        assert result["pages"] == 0
        assert result["items"] == []

    def test_sqlalchemy_query_delegation(self, app):
        """Paginate delegates to .offset().limit() for SQLAlchemy queries."""
        from unittest.mock import MagicMock

        from penguin_libs.flask import paginate

        mock_query = MagicMock()
        mock_query.count.return_value = 50
        mock_query.offset.return_value.limit.return_value.all.return_value = [
            {"id": i} for i in range(10)
        ]

        result = paginate(mock_query, page=2, per_page=10)
        mock_query.count.assert_called_once()
        mock_query.offset.assert_called_once_with(10)  # (page-1)*per_page
        assert result["total"] == 50
        assert result["pages"] == 5
        assert len(result["items"]) == 10

    def test_page_clamps_to_1(self, app):
        """Page 0 or negative is treated as page 1."""
        from penguin_libs.flask import paginate

        result = paginate(list(range(10)), page=0, per_page=5)
        assert result["page"] == 1
        assert result["items"] == list(range(5))
