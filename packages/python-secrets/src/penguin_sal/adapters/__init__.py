"""Adapter registry with lazy loading for secrets backends.

Adapters are loaded on demand to avoid requiring all backend SDKs
to be installed. When an adapter's dependency is missing, a helpful
AdapterNotInstalledError is raised with install instructions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin_sal.core.exceptions import AdapterNotInstalledError, InvalidURIError

if TYPE_CHECKING:
    from penguin_sal.core.base_adapter import BaseAdapter

# Registry mapping scheme names to (module_path, class_name, install_extra)
_ADAPTER_REGISTRY: dict[str, tuple[str, str, str]] = {
    "vault": ("penguin_sal.adapters.vault", "VaultAdapter", "vault"),
    "infisical": (
        "penguin_sal.adapters.infisical",
        "InfisicalAdapter",
        "infisical",
    ),
    "cyberark": (
        "penguin_sal.adapters.cyberark",
        "CyberArkAdapter",
        "cyberark",
    ),
    "aws-sm": (
        "penguin_sal.adapters.aws_sm",
        "AWSSecretsManagerAdapter",
        "aws",
    ),
    "gcp-sm": (
        "penguin_sal.adapters.gcp_sm",
        "GCPSecretManagerAdapter",
        "gcp",
    ),
    "azure-kv": (
        "penguin_sal.adapters.azure_kv",
        "AzureKeyVaultAdapter",
        "azure",
    ),
    "oci-vault": (
        "penguin_sal.adapters.oci_vault",
        "OCIVaultAdapter",
        "oci",
    ),
    "k8s": (
        "penguin_sal.adapters.k8s_secrets",
        "KubernetesSecretsAdapter",
        "k8s",
    ),
    "1password": (
        "penguin_sal.adapters.onepassword",
        "OnePasswordAdapter",
        "onepassword",
    ),
    "passbolt": (
        "penguin_sal.adapters.passbolt",
        "PassboltAdapter",
        "passbolt",
    ),
    "doppler": (
        "penguin_sal.adapters.doppler",
        "DopplerAdapter",
        "doppler",
    ),
}


def get_adapter_class(scheme: str) -> type[BaseAdapter]:
    """Get the adapter class for a given URI scheme.

    Lazily imports the adapter module to avoid requiring all backend
    SDKs to be installed.

    Args:
        scheme: The URI scheme (e.g., 'vault', 'aws-sm').

    Returns:
        The adapter class (not an instance).

    Raises:
        InvalidURIError: If the scheme is not recognized.
        AdapterNotInstalledError: If the adapter's SDK is not
            installed.
    """
    if scheme not in _ADAPTER_REGISTRY:
        raise InvalidURIError(
            f"{scheme}://...",
            f"unsupported scheme '{scheme}', "
            f"must be one of: {', '.join(sorted(_ADAPTER_REGISTRY))}",
        )

    module_path, class_name, install_extra = _ADAPTER_REGISTRY[scheme]

    try:
        import importlib

        module = importlib.import_module(module_path)
    except ImportError as e:
        raise AdapterNotInstalledError(scheme, install_extra) from e

    return getattr(module, class_name)  # type: ignore[no-any-return]


def list_backends() -> list[str]:
    """Return a sorted list of all supported backend scheme names."""
    return sorted(_ADAPTER_REGISTRY.keys())
