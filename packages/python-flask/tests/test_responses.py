"""Tests for response envelope helpers."""

import json
from typing import Any

import pytest
from flask import Flask

from penguin_flask.responses import error_response, success_response


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
