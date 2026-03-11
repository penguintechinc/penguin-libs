# penguin-licensing

PenguinTech License Server Python client. Validates licenses, checks feature entitlements, and provides Flask decorators for license/feature gating.

## Installation

```bash
pip install penguin-licensing

# With Flask extras:
pip install penguin-licensing[flask]
```

## Quick Start

```python
from penguin_licensing import LicenseClient

client = LicenseClient(
    license_key="PENG-XXXX-XXXX-XXXX-XXXX-ABCD",
    product="my-app",
)

info = client.validate()
print(f"Valid: {info.valid}, Tier: {info.tier}, Customer: {info.customer}")

if client.check_feature("advanced_analytics"):
    # Feature is available
    pass
```

## Environment Variables

```bash
LICENSE_KEY=PENG-XXXX-XXXX-XXXX-XXXX-ABCD
PRODUCT_NAME=my-app
LICENSE_SERVER_URL=https://license.penguintech.io
```

## Flask Decorators

```python
from penguin_licensing.decorators import license_required, feature_required

@app.route('/api/v1/reports')
@feature_required('advanced_analytics')
def analytics():
    return {"data": "..."}

@app.route('/api/v1/enterprise')
@license_required('enterprise')
def enterprise_endpoint():
    return {"message": "Enterprise feature"}
```

📚 Full documentation: [docs/penguin-licensing/](../../docs/penguin-licensing/)
