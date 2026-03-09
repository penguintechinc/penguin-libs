"""Tests for adapter registry (adapters/__init__.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from penguin_sal.adapters import _ADAPTER_REGISTRY, get_adapter_class, list_backends
from penguin_sal.core.exceptions import AdapterNotInstalledError, InvalidURIError


class TestGetAdapterClass:
    """Test get_adapter_class lazy loading."""

    def test_unsupported_scheme_raises_invalid_uri_error(self) -> None:
        with pytest.raises(InvalidURIError, match="unsupported scheme 'nosuch'"):
            get_adapter_class("nosuch")

    def test_unsupported_scheme_lists_valid_schemes(self) -> None:
        with pytest.raises(InvalidURIError, match="must be one of"):
            get_adapter_class("redis")

    def test_import_error_raises_adapter_not_installed(self) -> None:
        """When the adapter module can't be imported, raise AdapterNotInstalledError."""
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            with pytest.raises(AdapterNotInstalledError, match="vault"):
                get_adapter_class("vault")

    def test_adapter_not_installed_has_install_instructions(self) -> None:
        with patch("importlib.import_module", side_effect=ImportError("missing")):
            with pytest.raises(AdapterNotInstalledError, match="pip install"):
                get_adapter_class("aws-sm")

    def test_successful_import_returns_class(self) -> None:
        """When import succeeds, returns the class from the module."""
        mock_module = MagicMock()
        mock_class = type("VaultAdapter", (), {})
        mock_module.VaultAdapter = mock_class

        with patch("importlib.import_module", return_value=mock_module):
            result = get_adapter_class("vault")
            assert result is mock_class

    def test_successful_import_calls_importlib(self) -> None:
        mock_module = MagicMock()
        mock_module.AWSSecretsManagerAdapter = MagicMock()

        with patch("importlib.import_module", return_value=mock_module) as mock_import:
            get_adapter_class("aws-sm")
            mock_import.assert_called_once_with("penguin_sal.adapters.aws_sm")

    def test_all_registry_schemes_have_three_tuple(self) -> None:
        """Each registry entry has (module_path, class_name, install_extra)."""
        for scheme, entry in _ADAPTER_REGISTRY.items():
            assert len(entry) == 3, f"Registry entry for {scheme} should be a 3-tuple"
            module_path, class_name, install_extra = entry
            assert isinstance(module_path, str)
            assert isinstance(class_name, str)
            assert isinstance(install_extra, str)

    def test_each_registered_scheme_import_error_path(self) -> None:
        """Every registered scheme raises AdapterNotInstalledError on ImportError."""
        for scheme in _ADAPTER_REGISTRY:
            with patch("importlib.import_module", side_effect=ImportError("test")):
                with pytest.raises(AdapterNotInstalledError):
                    get_adapter_class(scheme)


class TestListBackends:
    """Test list_backends function."""

    def test_returns_sorted_list(self) -> None:
        result = list_backends()
        assert result == sorted(result)

    def test_returns_list_type(self) -> None:
        result = list_backends()
        assert isinstance(result, list)

    def test_contains_all_registry_keys(self) -> None:
        result = list_backends()
        assert set(result) == set(_ADAPTER_REGISTRY.keys())

    def test_count_matches_registry(self) -> None:
        result = list_backends()
        assert len(result) == len(_ADAPTER_REGISTRY)


class TestAdapterRegistry:
    """Test the _ADAPTER_REGISTRY constant."""

    def test_registry_has_eleven_entries(self) -> None:
        assert len(_ADAPTER_REGISTRY) == 11

    def test_known_schemes_present(self) -> None:
        expected = {
            "vault", "infisical", "cyberark", "aws-sm", "gcp-sm",
            "azure-kv", "oci-vault", "k8s", "1password", "passbolt", "doppler",
        }
        assert set(_ADAPTER_REGISTRY.keys()) == expected
