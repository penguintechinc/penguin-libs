"""Shared pytest fixtures and helpers for PenguinTech Python packages."""

from penguin_pytest.asgi import asgi_http_scope, asgi_ok_app, asgi_send_collector
from penguin_pytest.dal import dal_db, sqlite_engine, users_posts_engine
from penguin_pytest.flask import flask_app, flask_client
from penguin_pytest.grpc import grpc_handler_call_details, mock_grpc_module

__all__ = [
    # ASGI helpers
    "asgi_http_scope",
    "asgi_ok_app",
    "asgi_send_collector",
    # gRPC helpers
    "grpc_handler_call_details",
    "mock_grpc_module",
    # DAL fixtures
    "dal_db",
    "sqlite_engine",
    "users_posts_engine",
    # Flask fixtures
    "flask_app",
    "flask_client",
]
