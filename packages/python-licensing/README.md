# Penguin Tech License Client

PenguinTech License Server Python client for license validation and feature gating.

## Installation

```bash
pip install penguin-licensing

# With Flask extras
pip install penguin-licensing[flask]
```

## Usage

### Basic License Validation

```python
from penguin_licensing import LicenseClient

# Initialize client
client = LicenseClient(
    license_key="PENG-XXXX-XXXX-XXXX-XXXX-ABCD",
    product="elder"
)

# Validate license
info = client.validate()
print(f"License valid: {info.valid}")
print(f"Customer: {info.customer}")
print(f"Tier: {info.tier}")
```

### Feature Gating

```python
from penguin_licensing import get_license_client

client = get_license_client()

# Check specific feature
if client.check_feature("advanced_analytics"):
    # Feature is available
    pass

# Check tier requirement
if client.check_tier("enterprise"):
    # Has enterprise license or higher
    pass
```

### Exceptions

The decorators are framework-agnostic: on denial they **raise**, they do not
return an HTTP response. Catch these and map them to whatever your framework
uses. All three are exported from the package root and are the same classes
raised by every module in it.

| Exception | Raised by | Attributes |
|---|---|---|
| `LicenseRequiredError` | `@license_required` | `required_tier`, `current_tier` |
| `FeatureNotAvailableError` | `@feature_required`, `@requires_feature` | `feature` |
| `LicenseValidationError` | `PenguinTechLicenseClient.validate()` | — |

```python
from penguin_licensing import (
    FeatureNotAvailableError,
    LicenseRequiredError,
    LicenseValidationError,
)
```

### Flask Integration

Register error handlers so a denied license becomes a `403`, not an unhandled
`500`:

```python
from flask import Flask, jsonify
from penguin_licensing import FeatureNotAvailableError, LicenseRequiredError
from penguin_licensing.decorators import feature_required, license_required

app = Flask(__name__)


@app.errorhandler(LicenseRequiredError)
def handle_license_required(err):
    return (
        jsonify(
            {
                "error": "license_required",
                "message": str(err),
                "required_tier": err.required_tier,
                "current_tier": err.current_tier,
            }
        ),
        403,
    )


@app.errorhandler(FeatureNotAvailableError)
def handle_feature_not_available(err):
    return (
        jsonify(
            {
                "error": "feature_not_available",
                "message": str(err),
                "feature": err.feature,
            }
        ),
        403,
    )


@app.route('/api/v1/enterprise-feature')
@license_required('enterprise')
def enterprise_endpoint():
    return {"message": "Enterprise feature"}


@app.route('/api/v1/analytics')
@feature_required('advanced_analytics')
def analytics_endpoint():
    return {"data": "analytics"}
```

Quart is identical — `@app.errorhandler(...)` with `async def` handlers.

### Transport & Failure Behaviour

- **HTTPS is enforced** on the license server URL for every non-loopback host;
  a plaintext URL raises `ValueError` at client construction.
- **Definitive rejection** (`401`/`403`/`404`) drops any cached entitlement, so
  a revoked license degrades to community immediately.
- **Server outage** (`5xx`, timeouts, connection errors) returns the last
  known-good cached validation; with no cache the client degrades to community
  (`LicenseClient`) or raises `LicenseValidationError`
  (`PenguinTechLicenseClient`).
- Pass `validate(force_refresh=True)` to bypass the 5-minute validation cache.

### Environment Variables

```bash
LICENSE_KEY=PENG-XXXX-XXXX-XXXX-XXXX-ABCD
PRODUCT_NAME=elder
LICENSE_SERVER_URL=https://license.penguintech.io
```

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

MIT - See [LICENSE](../../LICENSE) for details.
