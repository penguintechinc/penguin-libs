# penguin-sal

Secrets and Adapters Library for Python. Provides a unified interface for reading secrets from multiple backends: environment variables, HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, and Azure Key Vault.

## Installation

```bash
pip install penguin-sal
```

## Quick Start

```python
from penguin_sal import get_secret

# Auto-detects backend from environment
db_pass = get_secret("DB_PASS")
api_key = get_secret("API_KEY")
```

## Backends

| Backend | Description | Env var to activate |
|---------|-------------|---------------------|
| Environment | Read from `os.environ` | (default) |
| HashiCorp Vault | `hvac` client | `VAULT_ADDR` + `VAULT_TOKEN` |
| AWS Secrets Manager | `boto3` | `AWS_SECRET_BACKEND=aws` |
| GCP Secret Manager | `google-cloud-secret-manager` | `GCP_SECRET_BACKEND=gcp` |
| Azure Key Vault | `azure-keyvault-secrets` | `AZURE_SECRET_BACKEND=azure` |

## Usage

```python
from penguin_sal.core import SecretsManager
from penguin_sal.adapters import VaultAdapter

manager = SecretsManager(adapter=VaultAdapter(
    addr="https://vault.example.com",
    token="s.xxxx",
    mount="secret",
))

db_pass = manager.get("myapp/db_pass")
```

📚 Full documentation: [docs/penguin-sal/](../../docs/penguin-sal/)
