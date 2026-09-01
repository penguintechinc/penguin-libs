"""Flask integration for Pydantic 2 validation.

Flask is an optional extra (``pip install penguin-security[flask]``) --
this module must import cleanly without Flask installed so that
``import penguin_security`` never forces Flask on consumers who only need
e.g. sanitize/password/crypto. Every Flask symbol is therefore imported
locally, inside the function that needs it; only calling one of these
functions without Flask installed raises ImportError.
"""

# flake8: noqa: E501

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from flask import Response

T = TypeVar("T", bound=BaseModel)


class ValidationErrorResponse:
    """Standardized validation error response for Flask."""

    @staticmethod
    def from_pydantic_error(error: ValidationError) -> tuple[dict[str, Any], int]:
        """Convert Pydantic ValidationError to Flask response tuple.

        Args:
            error: Pydantic ValidationError instance

        Returns:
            Tuple of (error dict, status code)
        """
        # Log validation errors for debugging. include_input=False/
        # include_url=False keep raw submitted field values (passwords,
        # tokens, any sensitive body field) out of both the log line and
        # the per-field error dict below -- pydantic's default
        # ValidationError.errors() embeds the submitted value verbatim.
        from flask import current_app, has_app_context

        safe_errors = error.errors(include_input=False, include_url=False)

        if has_app_context() and current_app:
            current_app.logger.error(f"Validation error: {safe_errors}")

        validation_errors = []
        for err in safe_errors:
            validation_errors.append(
                {
                    "field": ".".join(str(x) for x in err["loc"]),
                    "message": err["msg"],
                    "type": err["type"],
                }
            )

        return {
            "error": "Validation failed",
            "validation_errors": validation_errors,
        }, 400


def validate_body[T: BaseModel](model_class: type[T]) -> T:
    """Validate request body against Pydantic model.

    Args:
        model_class: Pydantic model class to validate against

    Returns:
        Validated model instance

    Raises:
        ValidationError: If validation fails
    """
    from flask import request

    data = request.get_json()
    return model_class.model_validate(data)


def validate_query_params[T: BaseModel](model_class: type[T]) -> T:
    """Validate query parameters against Pydantic model.

    Args:
        model_class: Pydantic model class to validate against

    Returns:
        Validated model instance

    Raises:
        ValidationError: If validation fails
    """
    from flask import request

    data = request.args.to_dict()
    return model_class.model_validate(data)


def validated_request(
    body_model: type[BaseModel] | None = None,
    query_model: type[BaseModel] | None = None,
) -> Callable:
    """Decorator that validates request body and/or query parameters.

    Injects validated models as 'body' and/or 'query' keyword arguments.

    Args:
        body_model: Optional Pydantic model for request body validation
        query_model: Optional Pydantic model for query parameter validation

    Returns:
        Decorated function with validation

    Example:
        @app.route('/users', methods=['POST'])
        @validated_request(body_model=CreateUserRequest, query_model=PaginationParams)
        def create_user(body: CreateUserRequest, query: PaginationParams):
            return {"user": body.model_dump(), "page": query.page}
    """

    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    if body_model:
                        kwargs["body"] = validate_body(body_model)
                    if query_model:
                        kwargs["query"] = validate_query_params(query_model)

                    return await func(*args, **kwargs)
                except ValidationError as e:
                    return ValidationErrorResponse.from_pydantic_error(e)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    if body_model:
                        kwargs["body"] = validate_body(body_model)
                    if query_model:
                        kwargs["query"] = validate_query_params(query_model)

                    return func(*args, **kwargs)
                except ValidationError as e:
                    return ValidationErrorResponse.from_pydantic_error(e)

            return sync_wrapper

    return decorator


def model_response(
    model: BaseModel, status_code: int = 200, exclude_none: bool = True
) -> tuple[Response, int]:
    """Convert Pydantic model to Flask JSON response.

    Args:
        model: Pydantic model instance to serialize
        status_code: HTTP status code (default: 200)
        exclude_none: Whether to exclude None values from output (default: True)

    Returns:
        Tuple of (Flask Response, status code)

    Example:
        @app.route('/users/<int:user_id>')
        def get_user(user_id: int):
            user = UserResponse(id=user_id, name="Alice", email="alice@example.com")
            return model_response(user)
    """
    from flask import Response, has_app_context, jsonify

    data = model.model_dump(exclude_none=exclude_none)

    # If we're in an app context, use jsonify for proper Flask Response
    if has_app_context():
        return jsonify(data), status_code

    # Otherwise, create a mock Response for testing
    response = Response()
    response.set_data(__import__("json").dumps(data))
    response.headers["Content-Type"] = "application/json"
    return response, status_code
