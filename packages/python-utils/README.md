# Penguin Tech Python Utilities

Shared Python utilities for Penguin Tech applications.

## Installation

```bash
pip install penguintechinc-utils

# With Flask extras
pip install penguintechinc-utils[flask]
```

## Usage

### Sanitized Logging

```python
from penguintechinc_utils import get_logger, sanitize_log_data
from penguintechinc_utils.logging import SanitizedLogger

# Simple logger
log = SanitizedLogger("MyComponent")

# Automatically sanitizes sensitive data
log.info("User login attempt", {
    "email": "user@example.com",  # Logs as: [email]@example.com
    "password": "secret123",       # Logs as: [REDACTED]
    "remember_me": True,           # Logs as-is
})

# Output: [MyComponent] INFO: User login attempt {'email': '[email]@example.com', 'password': '[REDACTED]', 'remember_me': True}
```

### Sanitization Rules

The following are automatically redacted:
- Passwords, secrets, tokens
- API keys, auth tokens
- MFA/TOTP codes
- Session IDs, cookies
- Full email addresses (only domain is logged)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src tests
ruff check src tests

# Type check
mypy src
```

## License

AGPL-3.0 - See [LICENSE](../../LICENSE) for details.
