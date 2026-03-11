"""Register penguin_pytest fixtures for the package's own test suite."""

pytest_plugins = [
    "penguin_pytest.asgi",
    "penguin_pytest.grpc",
    "penguin_pytest.dal",
    "penguin_pytest.flask",
]
