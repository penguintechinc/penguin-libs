"""Penguin-DAL exceptions."""


class DALError(Exception):
    """Base exception for Penguin-DAL."""


class TableNotFoundError(DALError):
    """Raised when accessing a table that does not exist in the database."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        super().__init__(f"Table '{table_name}' not found in database")


class ValidationError(DALError):
    """Raised when data fails validation before insert/update."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        messages = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
        super().__init__(f"Validation failed: {messages}")


class UnsupportedOperationError(DALError):
    """Raised when a backend does not support the requested operation."""

    def __init__(self, backend: str, operation: str) -> None:
        super().__init__(f"Backend '{backend}' does not support operation '{operation}'")


class BackendConnectionError(DALError):
    """Raised when a backend connection fails."""

    def __init__(self, backend: str, reason: str) -> None:
        super().__init__(f"Failed to connect to backend '{backend}': {reason}")
