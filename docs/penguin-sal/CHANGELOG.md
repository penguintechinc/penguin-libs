# penguin-sal Changelog

## 0.1.0

- Initial release
- `get_secret()` top-level convenience function with auto-detection
- `SecretsManager` with pluggable adapter pattern
- Adapters: `EnvAdapter`, `VaultAdapter`, `AWSAdapter`, `GCPAdapter`, `AzureAdapter`
- Environment variable-based backend selection
