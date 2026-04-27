"""Integration tests with Flask test client."""

from flask import Flask

from penguin_flask import error_response, paginate, success_response


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
        from penguin_flask import get_pagination_params

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
        from penguin_flask import get_pagination_params

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
