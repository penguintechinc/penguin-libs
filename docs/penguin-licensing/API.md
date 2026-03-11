# penguin-licensing API Reference

## LicenseClient

```python
LicenseClient(
    license_key: str | None = None,   # defaults to LICENSE_KEY env var
    product: str | None = None,        # defaults to PRODUCT_NAME env var
    server_url: str | None = None,     # defaults to LICENSE_SERVER_URL env var
)
```

### Methods

| Method | Description |
|--------|-------------|
| `client.validate() -> LicenseInfo` | Validate the license key against the server |
| `client.check_feature(feature: str) -> bool` | Return `True` if feature is entitled |
| `client.check_tier(tier: str) -> bool` | Return `True` if license tier meets requirement |
| `client.keepalive(usage: dict | None = None)` | Report usage statistics to license server |

## LicenseInfo

```python
@dataclass(slots=True)
class LicenseInfo:
    valid: bool
    customer: str
    tier: str                   # "community", "professional", "enterprise"
    features: list[str]
    expires_at: str | None
    max_seats: int | None
```

## get_license_client

```python
get_license_client() -> LicenseClient
```

Returns the global singleton `LicenseClient`. Initializes from environment variables on first call.

## Flask Decorators

```python
from penguin_licensing.decorators import license_required, feature_required
```

### license_required

```python
@license_required(tier: str)
```

Decorator that returns HTTP 402 if the current license does not meet the required tier. Tiers (ascending): `"community"`, `"professional"`, `"enterprise"`.

### feature_required

```python
@feature_required(feature: str)
```

Decorator that returns HTTP 402 if the feature is not included in the current license.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LICENSE_KEY` | License key (`PENG-XXXX-...`) | — |
| `PRODUCT_NAME` | Product identifier | — |
| `LICENSE_SERVER_URL` | License server base URL | `https://license.penguintech.io` |
| `RELEASE_MODE` | `true` enables license enforcement | `false` |
