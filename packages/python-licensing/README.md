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

### Flask Integration

```python
from flask import Flask
from penguin_licensing.decorators import license_required, feature_required

app = Flask(__name__)

@app.route('/api/v1/enterprise-feature')
@license_required('enterprise')
def enterprise_endpoint():
    return {"message": "Enterprise feature"}

@app.route('/api/v1/analytics')
@feature_required('advanced_analytics')
def analytics_endpoint():
    return {"data": "analytics"}
```

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

AGPL-3.0 - See [LICENSE](../../LICENSE) for details.
