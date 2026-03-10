# penguin-sal API Reference

## get_secret

```python
get_secret(key: str, default: str | None = None) -> str | None
```

Top-level convenience function. Reads `key` from the auto-detected secret backend. Returns `default` if the key is not found.

## SecretsManager

```python
SecretsManager(adapter: Adapter)
```

| Method | Description |
|--------|-------------|
| `manager.get(key: str) -> str \| None` | Get a secret by key |
| `manager.set(key: str, value: str)` | Set a secret (if backend supports write) |
| `manager.delete(key: str)` | Delete a secret (if backend supports delete) |

## Adapters

### EnvAdapter (default)

Reads secrets from `os.environ`.

```python
from penguin_sal.adapters import EnvAdapter
SecretsManager(adapter=EnvAdapter())
```

### VaultAdapter

```python
from penguin_sal.adapters import VaultAdapter

VaultAdapter(
    addr: str,         # e.g. "https://vault.example.com"
    token: str,        # Vault token
    mount: str = "secret",
)
```

### AWSAdapter

```python
from penguin_sal.adapters import AWSAdapter

AWSAdapter(
    region: str = "us-east-1",
    prefix: str | None = None,   # Optional key prefix
)
```

### GCPAdapter

```python
from penguin_sal.adapters import GCPAdapter

GCPAdapter(project_id: str)
```

### AzureAdapter

```python
from penguin_sal.adapters import AzureAdapter

AzureAdapter(vault_url: str)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VAULT_ADDR` | Vault server address (activates `VaultAdapter`) |
| `VAULT_TOKEN` | Vault authentication token |
| `AWS_SECRET_BACKEND` | Set to `aws` to use `AWSAdapter` |
| `GCP_SECRET_BACKEND` | Set to `gcp` to use `GCPAdapter` |
| `AZURE_SECRET_BACKEND` | Set to `azure` to use `AzureAdapter` |
