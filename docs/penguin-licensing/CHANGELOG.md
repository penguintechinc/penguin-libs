# penguin-licensing Changelog

## 0.1.0

- Initial release
- `LicenseClient` with `validate()`, `check_feature()`, `check_tier()`, `keepalive()`
- `LicenseInfo` dataclass
- `get_license_client()` global singleton factory
- Flask decorators: `license_required`, `feature_required`
- `RELEASE_MODE` environment variable for development/production toggle
- Connects to `https://license.penguintech.io` by default
