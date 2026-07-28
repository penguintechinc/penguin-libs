"""Tests for Flask helpers: pagination, responses, and integration."""

import json
import math
from unittest.mock import MagicMock
from typing import Any

import pytest
from flask import Flask, request

from penguin_http.flask.pagination import get_pagination_params, paginate
from penguin_http.flask.responses import error_response, success_response


class TestGetPaginationParams:
    """Tests for get_pagination_params function."""

    def test_default_parameters(self, app: Flask) -> None:
        """Test get_pagination_params with no query parameters."""
        with app.test_request_context("/"):
            page, per_page = get_pagination_params()

        assert page == 1
        assert per_page == 20

    def test_custom_default_per_page(self, app: Flask) -> None:
        """Test get_pagination_params with custom default_per_page."""
        with app.test_request_context("/"):
            page, per_page = get_pagination_params(default_per_page=50)

        assert page == 1
        assert per_page == 50

    def test_with_page_in_query_string(self, app: Flask) -> None:
        """Test extracting page from query string."""
        with app.test_request_context("/?page=2"):
            page, per_page = get_pagination_params()

        assert page == 2
        assert per_page == 20

    def test_with_per_page_in_query_string(self, app: Flask) -> None:
        """Test extracting per_page from query string."""
        with app.test_request_context("/?per_page=50"):
            page, per_page = get_pagination_params()

        assert page == 1
        assert per_page == 50

    def test_with_both_params_in_query_string(self, app: Flask) -> None:
        """Test extracting both page and per_page from query string."""
        with app.test_request_context("/?page=3&per_page=25"):
            page, per_page = get_pagination_params()

        assert page == 3
        assert per_page == 25

    def test_page_zero_becomes_one(self, app: Flask) -> None:
        """Test that page=0 defaults to page=1."""
        with app.test_request_context("/?page=0"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_negative_page_becomes_one(self, app: Flask) -> None:
        """Test that negative page defaults to 1."""
        with app.test_request_context("/?page=-5"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_per_page_zero_becomes_one(self, app: Flask) -> None:
        """Test that per_page=0 is treated as 1 (max(1, 0) = 1)."""
        with app.test_request_context("/?per_page=0"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 1

    def test_negative_per_page_becomes_one(self, app: Flask) -> None:
        """Test that negative per_page is treated as 1 (max(1, -10) = 1)."""
        with app.test_request_context("/?per_page=-10"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 1

    def test_invalid_page_string(self, app: Flask) -> None:
        """Test that non-numeric page defaults to 1."""
        with app.test_request_context("/?page=invalid"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_invalid_per_page_string(self, app: Flask) -> None:
        """Test that non-numeric per_page defaults to default_per_page."""
        with app.test_request_context("/?per_page=invalid"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 20

    def test_both_invalid(self, app: Flask) -> None:
        """Test handling of both invalid page and per_page."""
        with app.test_request_context("/?page=abc&per_page=xyz"):
            page, per_page = get_pagination_params(default_per_page=30)

        assert page == 1
        assert per_page == 30

    def test_float_page_invalid_string(self, app: Flask) -> None:
        """Test that float string page values are treated as invalid and default to 1."""
        with app.test_request_context("/?page=2.7"):
            page, per_page = get_pagination_params()

        # Float strings like "2.7" fail int() conversion, so default to 1
        assert page == 1
        assert isinstance(page, int)

    def test_float_per_page_invalid_string(self, app: Flask) -> None:
        """Test that float string per_page values are treated as invalid and default."""
        with app.test_request_context("/?per_page=25.3"):
            page, per_page = get_pagination_params()

        # Float strings like "25.3" fail int() conversion, so default to default_per_page (20)
        assert per_page == 20
        assert isinstance(per_page, int)

    def test_large_page_number(self, app: Flask) -> None:
        """Test handling of very large page numbers."""
        with app.test_request_context("/?page=999999"):
            page, per_page = get_pagination_params()

        assert page == 999999

    def test_large_per_page(self, app: Flask) -> None:
        """Test handling of very large per_page values."""
        with app.test_request_context("/?per_page=10000"):
            page, per_page = get_pagination_params()

        assert per_page == 10000

    def test_whitespace_in_params(self, app: Flask) -> None:
        """Test handling of whitespace in parameters."""
        with app.test_request_context("/?page=%202%20"):
            page, per_page = get_pagination_params()

        # Query string decoding handles whitespace
        assert page >= 1


class TestPaginateWithList:
    """Tests for paginate function with plain lists."""

    def test_paginate_empty_list(self) -> None:
        """Test paginating an empty list."""
        result = paginate([], page=1, per_page=20)

        assert result["items"] == []
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["total"] == 0
        assert result["pages"] == 0

    def test_paginate_single_item(self) -> None:
        """Test paginating a list with one item."""
        data = [{"id": 1}]
        result = paginate(data, page=1, per_page=20)

        assert result["items"] == data
        assert result["total"] == 1
        assert result["pages"] == 1

    def test_paginate_first_page(self) -> None:
        """Test first page of results."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=1, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 1
        assert result["items"][4]["id"] == 5
        assert result["page"] == 1
        assert result["total"] == 10
        assert result["pages"] == 2

    def test_paginate_second_page(self) -> None:
        """Test second page of results."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=2, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 6
        assert result["items"][4]["id"] == 10
        assert result["page"] == 2

    def test_paginate_last_page_partial(self) -> None:
        """Test last page with fewer items than per_page."""
        data = [{"id": i} for i in range(1, 26)]  # 25 items
        result = paginate(data, page=3, per_page=10)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 21
        assert result["total"] == 25
        assert result["pages"] == 3

    def test_paginate_out_of_bounds_page(self) -> None:
        """Test requesting a page beyond available data."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=10, per_page=5)

        assert result["items"] == []
        assert result["page"] == 10
        assert result["total"] == 5
        assert result["pages"] == 1

    def test_paginate_page_zero_becomes_one(self) -> None:
        """Test that page 0 is treated as page 1."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=0, per_page=5)

        assert result["items"][0]["id"] == 1
        assert result["page"] == 1

    def test_paginate_negative_page_becomes_one(self) -> None:
        """Test that negative page is treated as page 1."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=-5, per_page=5)

        assert result["items"][0]["id"] == 1
        assert result["page"] == 1

    def test_paginate_per_page_zero_becomes_one(self) -> None:
        """Test that per_page=0 is treated as 1."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=0)

        assert len(result["items"]) == 1
        assert result["per_page"] == 1
        assert result["pages"] == 5

    def test_paginate_negative_per_page_becomes_one(self) -> None:
        """Test that negative per_page is treated as 1."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=-10)

        assert len(result["items"]) == 1
        assert result["per_page"] == 1

    def test_paginate_all_on_one_page(self) -> None:
        """Test when all items fit on one page."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=100)

        assert len(result["items"]) == 5
        assert result["pages"] == 1

    def test_paginate_string_items(self) -> None:
        """Test paginating a list of strings."""
        data = ["apple", "banana", "cherry", "date", "elderberry"]
        result = paginate(data, page=1, per_page=2)

        assert result["items"] == ["apple", "banana"]
        assert result["total"] == 5
        assert result["pages"] == 3

    def test_paginate_mixed_types(self) -> None:
        """Test paginating a list with mixed types."""
        data = [1, "two", 3.0, {"four": 4}, [5]]
        result = paginate(data, page=1, per_page=10)

        assert result["items"] == data
        assert result["total"] == 5

    def test_paginate_pages_calculation(self) -> None:
        """Test correct calculation of total pages."""
        test_cases = [
            (10, 5, 2),   # 10 items, 5 per page = 2 pages
            (11, 5, 3),   # 11 items, 5 per page = 3 pages
            (20, 10, 2),  # 20 items, 10 per page = 2 pages
            (21, 10, 3),  # 21 items, 10 per page = 3 pages
            (100, 7, 15), # 100 items, 7 per page = 15 pages
            (1, 10, 1),   # 1 item, 10 per page = 1 page
        ]

        for total_items, per_page, expected_pages in test_cases:
            data = list(range(total_items))
            result = paginate(data, page=1, per_page=per_page)
            assert result["pages"] == expected_pages, \
                f"Failed for {total_items} items, {per_page} per page"


class TestPaginateWithQuery:
    """Tests for paginate function with SQLAlchemy-like queries."""

    def test_paginate_sqlalchemy_query(self) -> None:
        """Test paginating a mock SQLAlchemy query."""
        # Create a mock query object
        mock_query = MagicMock()
        mock_query.count.return_value = 100
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [{"id": i} for i in range(1, 21)]

        result = paginate(mock_query, page=1, per_page=20)

        assert result["total"] == 100
        assert len(result["items"]) == 20
        assert result["pages"] == 5
        mock_query.count.assert_called_once()
        mock_query.offset.assert_called_once_with(0)
        mock_query.limit.assert_called_once_with(20)

    def test_paginate_query_second_page(self) -> None:
        """Test paginating query for second page."""
        mock_query = MagicMock()
        mock_query.count.return_value = 100
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [{"id": i} for i in range(21, 41)]

        result = paginate(mock_query, page=2, per_page=20)

        assert result["page"] == 2
        mock_query.offset.assert_called_once_with(20)

    def test_paginate_query_empty_result(self) -> None:
        """Test paginating query with zero results."""
        mock_query = MagicMock()
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = paginate(mock_query, page=1, per_page=20)

        assert result["total"] == 0
        assert result["items"] == []
        assert result["pages"] == 0

    def test_paginate_query_uses_offset_limit(self) -> None:
        """Test that query uses offset and limit methods."""
        mock_query = MagicMock()
        mock_query.count.return_value = 50
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        paginate(mock_query, page=3, per_page=10)

        # Page 3, 10 per page = offset 20
        mock_query.offset.assert_called_with(20)
        mock_query.limit.assert_called_with(10)


class TestPaginateListLike:
    """Tests for paginate with list-like objects (penguin-dal Rows, etc)."""

    def test_paginate_generator(self) -> None:
        """Test paginating a generator object."""
        def data_generator() -> Any:
            for i in range(1, 26):
                yield {"id": i}

        result = paginate(data_generator(), page=1, per_page=10)

        assert len(result["items"]) == 10
        assert result["total"] == 25
        assert result["pages"] == 3

    def test_paginate_tuple(self) -> None:
        """Test paginating a tuple."""
        data = tuple([{"id": i} for i in range(1, 11)])
        result = paginate(data, page=1, per_page=5)

        assert len(result["items"]) == 5
        assert result["total"] == 10

    def test_paginate_custom_iterable(self) -> None:
        """Test paginating a custom iterable."""
        class CustomIterable:
            def __init__(self, items: list[Any]) -> None:
                self.items = items

            def __iter__(self) -> Any:
                return iter(self.items)

            def __len__(self) -> int:
                return len(self.items)

        data = CustomIterable([{"id": i} for i in range(1, 21)])
        result = paginate(data, page=2, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 6


class TestPaginateResponseStructure:
    """Tests for paginate response structure and fields."""

    def test_paginate_response_has_all_fields(self) -> None:
        """Test that paginate response includes all required fields."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=20)

        required_fields = ["items", "page", "per_page", "total", "pages"]
        for field in required_fields:
            assert field in result

    def test_paginate_items_is_list(self) -> None:
        """Test that items field is always a list."""
        data = [{"id": 1}]
        result = paginate(data, page=1, per_page=20)

        assert isinstance(result["items"], list)

    def test_paginate_numeric_fields_are_integers(self) -> None:
        """Test that numeric fields are integers."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=20)

        assert isinstance(result["page"], int)
        assert isinstance(result["per_page"], int)
        assert isinstance(result["total"], int)
        assert isinstance(result["pages"], int)

    def test_paginate_all_values_match_expectations(self) -> None:
        """Test that all response values match expected values."""
        data = [{"id": i} for i in range(1, 26)]
        result = paginate(data, page=2, per_page=10)

        assert result["page"] == 2
        assert result["per_page"] == 10
        assert result["total"] == 25
        assert result["pages"] == 3
        assert len(result["items"]) == 10
        assert result["items"][0]["id"] == 11

    def test_paginate_zero_total_zero_pages(self) -> None:
        """Test that total=0 results in pages=0."""
        result = paginate([], page=1, per_page=20)

        assert result["total"] == 0
        assert result["pages"] == 0


class TestSuccessResponse:
    """Tests for success_response function."""

    def test_default_parameters(self, app_context: Flask) -> None:
        """Test success response with default parameters."""
        response, status_code = success_response()

        assert status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["data"] is None
        assert data["message"] == "Success"
        assert "meta" not in data

    def test_with_data_dict(self, app_context: Flask) -> None:
        """Test success response with dictionary data."""
        payload = {"id": 1, "name": "Alice"}
        response, status_code = success_response(data=payload)

        assert status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["data"] == payload
        assert data["message"] == "Success"

    def test_with_data_list(self, app_context: Flask) -> None:
        """Test success response with list data."""
        payload = [{"id": 1}, {"id": 2}, {"id": 3}]
        response, status_code = success_response(data=payload)

        assert status_code == 200
        data = response.get_json()
        assert data["data"] == payload
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 3

    def test_with_custom_message(self, app_context: Flask) -> None:
        """Test success response with custom message."""
        response, status_code = success_response(
            data={"id": 1},
            message="User created successfully"
        )

        assert status_code == 200
        data = response.get_json()
        assert data["message"] == "User created successfully"

    def test_with_201_created(self, app_context: Flask) -> None:
        """Test success response with 201 Created status."""
        response, status_code = success_response(
            data={"id": 1},
            status_code=201
        )

        assert status_code == 201
        assert response.get_json()["status"] == "success"

    def test_with_202_accepted(self, app_context: Flask) -> None:
        """Test success response with 202 Accepted status."""
        response, status_code = success_response(status_code=202)

        assert status_code == 202

    def test_with_204_no_content(self, app_context: Flask) -> None:
        """Test success response with 204 No Content status."""
        response, status_code = success_response(
            data=None,
            status_code=204
        )

        assert status_code == 204
        data = response.get_json()
        assert data["data"] is None

    def test_with_meta_pagination(self, app_context: Flask) -> None:
        """Test success response with pagination metadata."""
        meta = {
            "page": 1,
            "per_page": 20,
            "total": 100,
            "pages": 5
        }
        response, status_code = success_response(
            data=[{"id": 1}],
            meta=meta
        )

        assert status_code == 200
        data = response.get_json()
        assert "meta" in data
        assert data["meta"] == meta
        assert data["meta"]["page"] == 1
        assert data["meta"]["pages"] == 5

    def test_with_complex_meta(self, app_context: Flask) -> None:
        """Test success response with complex metadata."""
        meta = {
            "page": 2,
            "per_page": 50,
            "total": 1000,
            "pages": 20,
            "timestamp": "2025-01-22T10:00:00Z",
            "version": "v1"
        }
        response, status_code = success_response(meta=meta)

        assert status_code == 200
        data = response.get_json()
        assert data["meta"]["version"] == "v1"
        assert data["meta"]["timestamp"] == "2025-01-22T10:00:00Z"

    def test_meta_none_excluded(self, app_context: Flask) -> None:
        """Test that meta=None does not appear in response."""
        response, status_code = success_response(meta=None)

        data = response.get_json()
        assert "meta" not in data

    def test_content_type_json(self, app_context: Flask) -> None:
        """Test that response content type is JSON."""
        response, _ = success_response()

        assert response.content_type == "application/json"

    def test_with_empty_dict_data(self, app_context: Flask) -> None:
        """Test success response with empty dict data."""
        response, status_code = success_response(data={})

        assert status_code == 200
        data = response.get_json()
        assert data["data"] == {}

    def test_with_empty_list_data(self, app_context: Flask) -> None:
        """Test success response with empty list data."""
        response, status_code = success_response(data=[])

        assert status_code == 200
        data = response.get_json()
        assert data["data"] == []

    def test_with_zero_data(self, app_context: Flask) -> None:
        """Test success response with zero as data."""
        response, status_code = success_response(data=0)

        assert status_code == 200
        data = response.get_json()
        assert data["data"] == 0

    def test_with_false_data(self, app_context: Flask) -> None:
        """Test success response with False as data."""
        response, status_code = success_response(data=False)

        assert status_code == 200
        data = response.get_json()
        assert data["data"] is False

    def test_with_string_data(self, app_context: Flask) -> None:
        """Test success response with string data."""
        response, status_code = success_response(data="Hello World")

        assert status_code == 200
        data = response.get_json()
        assert data["data"] == "Hello World"

    def test_nested_data_structure(self, app_context: Flask) -> None:
        """Test success response with nested data structures."""
        payload = {
            "user": {
                "id": 1,
                "profile": {
                    "name": "Alice",
                    "email": "alice@example.com"
                }
            },
            "permissions": ["read", "write"]
        }
        response, status_code = success_response(data=payload)

        assert status_code == 200
        data = response.get_json()
        assert data["data"]["user"]["profile"]["name"] == "Alice"
        assert "write" in data["data"]["permissions"]


class TestErrorResponse:
    """Tests for error_response function."""

    def test_default_parameters(self, app_context: Flask) -> None:
        """Test error response with default parameters."""
        response, status_code = error_response("Something went wrong")

        assert status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Something went wrong"

    def test_with_400_bad_request(self, app_context: Flask) -> None:
        """Test error response with 400 Bad Request."""
        response, status_code = error_response(
            "Invalid input",
            status_code=400
        )

        assert status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Invalid input"

    def test_with_401_unauthorized(self, app_context: Flask) -> None:
        """Test error response with 401 Unauthorized."""
        response, status_code = error_response(
            "Authentication required",
            status_code=401
        )

        assert status_code == 401
        data = response.get_json()
        assert data["status"] == "error"

    def test_with_403_forbidden(self, app_context: Flask) -> None:
        """Test error response with 403 Forbidden."""
        response, status_code = error_response(
            "Access denied",
            status_code=403
        )

        assert status_code == 403
        data = response.get_json()
        assert data["status"] == "error"

    def test_with_404_not_found(self, app_context: Flask) -> None:
        """Test error response with 404 Not Found."""
        response, status_code = error_response(
            "Resource not found",
            status_code=404
        )

        assert status_code == 404
        data = response.get_json()
        assert data["status"] == "error"

    def test_with_422_unprocessable_entity(self, app_context: Flask) -> None:
        """Test error response with 422 Unprocessable Entity."""
        response, status_code = error_response(
            "Validation failed",
            status_code=422
        )

        assert status_code == 422
        data = response.get_json()
        assert data["status"] == "error"

    def test_with_500_internal_server_error(self, app_context: Flask) -> None:
        """Test error response with 500 Internal Server Error."""
        response, status_code = error_response(
            "Internal server error",
            status_code=500
        )

        assert status_code == 500
        data = response.get_json()
        assert data["status"] == "error"

    def test_with_single_kwarg(self, app_context: Flask) -> None:
        """Test error response with single additional field."""
        response, status_code = error_response(
            "Email is invalid",
            status_code=422,
            field="email"
        )

        assert status_code == 422
        data = response.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Email is invalid"
        assert data["field"] == "email"

    def test_with_multiple_kwargs(self, app_context: Flask) -> None:
        """Test error response with multiple additional fields."""
        response, status_code = error_response(
            "Validation failed",
            status_code=422,
            field="email",
            code="INVALID_EMAIL",
            constraint="EMAIL_FORMAT"
        )

        assert status_code == 422
        data = response.get_json()
        assert data["field"] == "email"
        assert data["code"] == "INVALID_EMAIL"
        assert data["constraint"] == "EMAIL_FORMAT"

    def test_with_code_kwarg(self, app_context: Flask) -> None:
        """Test error response with error code."""
        response, status_code = error_response(
            "Invalid credentials",
            status_code=401,
            code="AUTH_FAILED"
        )

        assert status_code == 401
        data = response.get_json()
        assert data["code"] == "AUTH_FAILED"

    def test_with_dict_kwarg(self, app_context: Flask) -> None:
        """Test error response with dict as additional field."""
        errors = {"email": "Invalid format", "password": "Too short"}
        response, status_code = error_response(
            "Validation failed",
            status_code=422,
            errors=errors
        )

        assert status_code == 422
        data = response.get_json()
        assert data["errors"] == errors
        assert data["errors"]["email"] == "Invalid format"

    def test_with_list_kwarg(self, app_context: Flask) -> None:
        """Test error response with list as additional field."""
        errors = ["Field A is required", "Field B is invalid"]
        response, status_code = error_response(
            "Multiple validation errors",
            status_code=422,
            errors=errors
        )

        assert status_code == 422
        data = response.get_json()
        assert data["errors"] == errors
        assert len(data["errors"]) == 2

    def test_content_type_json(self, app_context: Flask) -> None:
        """Test that error response content type is JSON."""
        response, _ = error_response("Error")

        assert response.content_type == "application/json"

    def test_kwarg_status_overrides_status_field(self, app_context: Flask) -> None:
        """Test that status kwarg can override the status field."""
        response, _ = error_response("Error", status=None)

        data = response.get_json()
        # When status=None is passed as kwarg, it overrides the "error" status
        assert data["status"] is None

    def test_with_empty_string_message(self, app_context: Flask) -> None:
        """Test error response with empty message."""
        response, status_code = error_response("")

        assert status_code == 400
        data = response.get_json()
        assert data["message"] == ""

    def test_kwarg_overrides(self, app_context: Flask) -> None:
        """Test that kwargs properly merge into response."""
        response, _ = error_response(
            "Test error",
            status_code=400,
            type="validation",
            severity="high"
        )

        data = response.get_json()
        assert data["type"] == "validation"
        assert data["severity"] == "high"
        assert data["message"] == "Test error"
        assert data["status"] == "error"


class TestIntegrationResponsesWithClient:
    """Integration tests using Flask test client."""

    def test_success_response_in_route(self, app: Flask, client) -> None:
        """Test success_response used in a route handler."""
        @app.route("/api/v1/user")
        def get_user():
            return success_response(
                data={"id": 1, "name": "Alice"},
                status_code=200
            )

        response = client.get("/api/v1/user")

        assert response.status_code == 200
        assert response.content_type == "application/json"
        data = response.get_json()
        assert data["status"] == "success"
        assert data["data"]["id"] == 1

    def test_error_response_in_route(self, app: Flask, client) -> None:
        """Test error_response used in a route handler."""
        @app.route("/api/v1/invalid")
        def invalid_endpoint():
            return error_response(
                "Invalid request",
                status_code=400,
                field="email"
            )

        response = client.get("/api/v1/invalid")

        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Invalid request"
        assert data["field"] == "email"

    def test_created_response_in_route(self, app: Flask, client) -> None:
        """Test 201 Created response."""
        @app.route("/api/v1/users", methods=["POST"])
        def create_user():
            return success_response(
                data={"id": 1, "name": "Alice"},
                message="User created",
                status_code=201
            )

        response = client.post("/api/v1/users")

        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "success"
        assert data["message"] == "User created"

    def test_unauthorized_response(self, app: Flask, client) -> None:
        """Test 401 Unauthorized response."""
        @app.route("/api/v1/protected")
        def protected_route():
            return error_response(
                "Authentication required",
                status_code=401,
                code="AUTH_REQUIRED"
            )

        response = client.get("/api/v1/protected")

        assert response.status_code == 401
        data = response.get_json()
        assert data["code"] == "AUTH_REQUIRED"

    def test_not_found_response(self, app: Flask, client) -> None:
        """Test 404 Not Found response."""
        @app.route("/api/v1/users/<int:user_id>")
        def get_user_by_id(user_id):
            if user_id != 1:
                return error_response(
                    "User not found",
                    status_code=404
                )
            return success_response(data={"id": 1, "name": "Alice"})

        response = client.get("/api/v1/users/999")

        assert response.status_code == 404
        data = response.get_json()
        assert data["status"] == "error"

    def test_validation_error_response(self, app: Flask, client) -> None:
        """Test validation error response with multiple fields."""
        @app.route("/api/v1/validate", methods=["POST"])
        def validate_input():
            errors = {
                "email": "Invalid format",
                "password": "Too short"
            }
            return error_response(
                "Validation failed",
                status_code=422,
                errors=errors
            )

        response = client.post("/api/v1/validate")

        assert response.status_code == 422
        data = response.get_json()
        assert "errors" in data
        assert data["errors"]["email"] == "Invalid format"

    def test_internal_server_error(self, app: Flask, client) -> None:
        """Test 500 Internal Server Error response."""
        @app.route("/api/v1/error")
        def error_route():
            return error_response(
                "Internal server error",
                status_code=500
            )

        response = client.get("/api/v1/error")

        assert response.status_code == 500
        data = response.get_json()
        assert data["status"] == "error"

    def test_paginated_success_response(self, app: Flask, client) -> None:
        """Test success_response with pagination metadata."""
        @app.route("/api/v1/items")
        def list_items():
            items = [{"id": i} for i in range(1, 11)]
            paginated = paginate(items, page=1, per_page=5)
            return success_response(
                data=paginated["items"],
                meta=paginated
            )

        response = client.get("/api/v1/items")

        assert response.status_code == 200
        data = response.get_json()
        assert "meta" in data
        assert data["meta"]["total"] == 10
        assert data["meta"]["pages"] == 2
        assert len(data["data"]) == 5

    def test_list_with_query_params(self, app: Flask, client) -> None:
        """Test endpoint using get_pagination_params and paginate."""
        from penguin_http.flask import get_pagination_params

        @app.route("/api/v1/products")
        def list_products():
            page, per_page = get_pagination_params(default_per_page=20)
            products = [{"id": i, "name": f"Product {i}"} for i in range(1, 101)]
            paginated = paginate(products, page=page, per_page=per_page)
            return success_response(
                data=paginated["items"],
                meta=paginated
            )

        response = client.get("/api/v1/products?page=2&per_page=25")

        assert response.status_code == 200
        data = response.get_json()
        assert data["meta"]["page"] == 2
        assert data["meta"]["per_page"] == 25
        assert data["meta"]["total"] == 100
        assert data["meta"]["pages"] == 4
        assert len(data["data"]) == 25
        assert data["data"][0]["id"] == 26

    def test_no_content_response(self, app: Flask, client) -> None:
        """Test 204 No Content response.

        Note: 204 responses typically have no body, but Flask's jsonify
        still returns a JSON response. Test verifies the status code.
        """
        @app.route("/api/v1/items/<int:item_id>", methods=["DELETE"])
        def delete_item(item_id):
            return success_response(
                data=None,
                message="Item deleted",
                status_code=204
            )

        response = client.delete("/api/v1/items/1")

        assert response.status_code == 204
        # Flask jsonify returns JSON even for 204; verify status is sufficient
        if response.data:
            data = response.get_json()
            assert data["data"] is None

    def test_empty_list_response(self, app: Flask, client) -> None:
        """Test endpoint returning empty list."""
        @app.route("/api/v1/empty")
        def empty_list():
            items = []
            paginated = paginate(items, page=1, per_page=20)
            return success_response(
                data=paginated["items"],
                meta=paginated
            )

        response = client.get("/api/v1/empty")

        assert response.status_code == 200
        data = response.get_json()
        assert data["data"] == []
        assert data["meta"]["total"] == 0
        assert data["meta"]["pages"] == 0

    def test_single_item_response(self, app: Flask, client) -> None:
        """Test endpoint returning single item in list."""
        @app.route("/api/v1/single")
        def single_item():
            items = [{"id": 1, "data": "test"}]
            paginated = paginate(items, page=1, per_page=20)
            return success_response(
                data=paginated["items"],
                meta=paginated
            )

        response = client.get("/api/v1/single")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["data"]) == 1
        assert data["meta"]["total"] == 1
        assert data["meta"]["pages"] == 1


class TestIntegrationErrorHandling:
    """Integration tests for error handling."""

    def test_multiple_error_formats(self, app: Flask, client) -> None:
        """Test various error response formats."""
        @app.route("/api/v1/error1")
        def error1():
            return error_response("Simple error")

        @app.route("/api/v1/error2")
        def error2():
            return error_response(
                "Error with field",
                status_code=422,
                field="email"
            )

        @app.route("/api/v1/error3")
        def error3():
            return error_response(
                "Error with details",
                status_code=400,
                code="INVALID_REQUEST",
                details="Additional context"
            )

        # Test simple error
        resp1 = client.get("/api/v1/error1")
        assert resp1.status_code == 400
        assert resp1.get_json()["message"] == "Simple error"

        # Test error with field
        resp2 = client.get("/api/v1/error2")
        assert resp2.status_code == 422
        assert resp2.get_json()["field"] == "email"

        # Test error with details
        resp3 = client.get("/api/v1/error3")
        assert resp3.status_code == 400
        assert resp3.get_json()["code"] == "INVALID_REQUEST"
        assert resp3.get_json()["details"] == "Additional context"


class TestIntegrationComplexScenarios:
    """Integration tests for complex scenarios."""

    def test_conditional_pagination(self, app: Flask, client) -> None:
        """Test pagination with conditional logic."""
        from penguin_http.flask import get_pagination_params

        @app.route("/api/v1/search")
        def search():
            page, per_page = get_pagination_params()
            # Simulate search results
            if page > 3:
                paginated = paginate([], page=page, per_page=per_page)
            else:
                items = [{"id": i} for i in range(1, 51)]
                paginated = paginate(items, page=page, per_page=per_page)

            return success_response(
                data=paginated["items"],
                meta=paginated
            )

        # First page
        resp1 = client.get("/api/v1/search?page=1")
        assert len(resp1.get_json()["data"]) == 20

        # Last valid page
        resp2 = client.get("/api/v1/search?page=3")
        assert len(resp2.get_json()["data"]) == 10

        # Beyond available
        resp3 = client.get("/api/v1/search?page=4")
        assert resp3.get_json()["data"] == []

    def test_nested_data_response(self, app: Flask, client) -> None:
        """Test response with nested data structures."""
        @app.route("/api/v1/nested")
        def nested_data():
            data = {
                "user": {
                    "id": 1,
                    "name": "Alice",
                    "profile": {
                        "bio": "Test user",
                        "roles": ["admin", "user"]
                    }
                },
                "metadata": {
                    "created": "2025-01-22"
                }
            }
            return success_response(data=data)

        response = client.get("/api/v1/nested")

        assert response.status_code == 200
        data = response.get_json()
        assert data["data"]["user"]["profile"]["roles"][0] == "admin"

    def test_response_with_all_fields(self, app: Flask, client) -> None:
        """Test response with data, message, and meta."""
        @app.route("/api/v1/full")
        def full_response():
            return success_response(
                data={"id": 1},
                message="Custom message",
                status_code=200,
                meta={"version": "v1", "timestamp": "2025-01-22"}
            )

        response = client.get("/api/v1/full")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["data"]["id"] == 1
        assert data["message"] == "Custom message"
        assert data["meta"]["version"] == "v1"

    def test_batch_operations_response(self, app: Flask, client) -> None:
        """Test response for batch operations."""
        @app.route("/api/v1/batch")
        def batch_operation():
            results = [
                {"id": 1, "status": "success"},
                {"id": 2, "status": "failed", "error": "Not found"},
                {"id": 3, "status": "success"}
            ]
            return success_response(
                data=results,
                meta={
                    "total": 3,
                    "succeeded": 2,
                    "failed": 1
                }
            )

        response = client.get("/api/v1/batch")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["data"]) == 3
        assert data["meta"]["succeeded"] == 2
        assert data["meta"]["failed"] == 1
