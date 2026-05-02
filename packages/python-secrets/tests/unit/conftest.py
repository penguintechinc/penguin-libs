"""Pytest configuration for unit tests."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


# Create exception classes first
class MockNotFound(Exception):
    """Mock NotFound exception."""

    pass


class MockPermissionDenied(Exception):
    """Mock PermissionDenied exception."""

    pass


class MockUnauthenticated(Exception):
    """Mock Unauthenticated exception."""

    pass


class MockAlreadyExists(Exception):
    """Mock AlreadyExists exception."""

    pass


# Create mock modules that persist across all tests
_mock_api_core_exceptions = MagicMock()
_mock_api_core_exceptions.NotFound = MockNotFound
_mock_api_core_exceptions.PermissionDenied = MockPermissionDenied
_mock_api_core_exceptions.Unauthenticated = MockUnauthenticated
_mock_api_core_exceptions.AlreadyExists = MockAlreadyExists

_mock_secretmanager = MagicMock()

# Create google mock hierarchy
_mock_google = MagicMock()
_mock_google_cloud = MagicMock()
# CRITICAL: make google.cloud.secretmanager return our configured mock
_mock_google_cloud.secretmanager = _mock_secretmanager

# Inject into sys.modules before any imports
sys.modules["google"] = _mock_google
sys.modules["google.cloud"] = _mock_google_cloud
sys.modules["google.cloud.secretmanager"] = _mock_secretmanager
sys.modules["google.api_core"] = MagicMock()
sys.modules["google.api_core.exceptions"] = _mock_api_core_exceptions


@pytest.fixture(autouse=True)
def reset_gcp_mocks() -> None:
    """Reset GCP mocks before each test."""
    # Save the original SecretManagerServiceClient mock
    original_client = _mock_secretmanager.SecretManagerServiceClient

    # Reset all call history but keep the mock object itself
    if hasattr(_mock_secretmanager, 'reset_mock'):
        _mock_secretmanager.reset_mock()

    # Recreate SecretManagerServiceClient to be fresh for each test
    _mock_secretmanager.SecretManagerServiceClient = MagicMock()

    # Yield to let the test run
    yield

    # Clear side effects and return values after test to isolate tests
    _mock_secretmanager.SecretManagerServiceClient.reset_mock()
    _mock_secretmanager.SecretManagerServiceClient.side_effect = None
    _mock_secretmanager.SecretManagerServiceClient.return_value = MagicMock()


@pytest.fixture
def mock_secretmanager() -> MagicMock:
    """Provide the mock secretmanager module."""
    return _mock_secretmanager


@pytest.fixture
def mock_api_core_exceptions() -> MagicMock:
    """Provide the mock api_core.exceptions module."""
    return _mock_api_core_exceptions
