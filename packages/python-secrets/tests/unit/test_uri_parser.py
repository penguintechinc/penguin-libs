"""Tests for URI parser."""

from __future__ import annotations

import pytest

from penguin_sal.core.exceptions import InvalidURIError
from penguin_sal.core.uri_parser import SUPPORTED_SCHEMES, ParsedURI, parse_uri


class TestParseURI:
    """Test URI parsing for all supported backends."""

    def test_vault_basic(self) -> None:
        result = parse_uri("vault://vault.example.com:8200/secret?token=hvs.xxx")
        assert result.scheme == "vault"
        assert result.host == "vault.example.com"
        assert result.port == 8200
        assert result.path == "secret"
        assert result.params == {"token": "hvs.xxx"}

    def test_vault_approle(self) -> None:
        result = parse_uri(
            "vault://vault.example.com:8200/secret?approle_id=xxx&approle_secret=yyy"
        )
        assert result.scheme == "vault"
        assert result.params["approle_id"] == "xxx"
        assert result.params["approle_secret"] == "yyy"

    def test_aws_sm_with_profile(self) -> None:
        result = parse_uri("aws-sm://us-east-1?profile=prod")
        assert result.scheme == "aws-sm"
        assert result.host == "us-east-1"
        assert result.port is None
        assert result.params == {"profile": "prod"}

    def test_aws_sm_with_keys(self) -> None:
        result = parse_uri("aws-sm://us-east-1?access_key=xxx&secret_key=yyy")
        assert result.scheme == "aws-sm"
        assert result.params["access_key"] == "xxx"
        assert result.params["secret_key"] == "yyy"

    def test_gcp_sm(self) -> None:
        result = parse_uri("gcp-sm://my-project?credentials_path=/keys/gcp.json")
        assert result.scheme == "gcp-sm"
        assert result.host == "my-project"
        assert result.params["credentials_path"] == "/keys/gcp.json"

    def test_azure_kv(self) -> None:
        result = parse_uri(
            "azure-kv://my-vault-name?tenant_id=xxx&client_id=yyy&client_secret=zzz"
        )
        assert result.scheme == "azure-kv"
        assert result.host == "my-vault-name"
        assert result.params["tenant_id"] == "xxx"

    def test_oci_vault(self) -> None:
        result = parse_uri("oci-vault://compartment-ocid/vault-ocid?config_path=~/.oci/config")
        assert result.scheme == "oci-vault"
        assert result.host == "compartment-ocid"
        assert result.path == "vault-ocid"

    def test_k8s_simple(self) -> None:
        result = parse_uri("k8s://my-namespace")
        assert result.scheme == "k8s"
        assert result.host == "my-namespace"
        assert result.port is None
        assert result.params == {}

    def test_k8s_with_context(self) -> None:
        result = parse_uri("k8s://my-namespace?kubeconfig=/path/to/config&context=prod")
        assert result.scheme == "k8s"
        assert result.host == "my-namespace"
        assert result.params["kubeconfig"] == "/path/to/config"
        assert result.params["context"] == "prod"

    def test_onepassword(self) -> None:
        result = parse_uri("1password://connect-server:8080/vault-name?token=xxx")
        assert result.scheme == "1password"
        assert result.host == "connect-server"
        assert result.port == 8080
        assert result.path == "vault-name"
        assert result.params["token"] == "xxx"

    def test_infisical(self) -> None:
        result = parse_uri("infisical://app.infisical.com/project-id?token=xxx&env=production")
        assert result.scheme == "infisical"
        assert result.host == "app.infisical.com"
        assert result.path == "project-id"
        assert result.params["env"] == "production"

    def test_cyberark(self) -> None:
        result = parse_uri("cyberark://conjur.example.com/myorg?api_key=xxx")
        assert result.scheme == "cyberark"
        assert result.host == "conjur.example.com"
        assert result.path == "myorg"

    def test_passbolt(self) -> None:
        result = parse_uri(
            "passbolt://passbolt.example.com/resource-group"
            "?key_path=/path/to/key.asc&passphrase=xxx"
        )
        assert result.scheme == "passbolt"
        assert result.host == "passbolt.example.com"
        assert result.path == "resource-group"
        assert result.params["key_path"] == "/path/to/key.asc"

    def test_doppler(self) -> None:
        result = parse_uri("doppler://my-project/production?token=dp.xxx")
        assert result.scheme == "doppler"
        assert result.host == "my-project"
        assert result.path == "production"
        assert result.params["token"] == "dp.xxx"

    def test_with_username_password(self) -> None:
        result = parse_uri("vault://admin:secret@vault.example.com:8200/secret")
        assert result.username == "admin"
        assert result.password == "secret"
        assert result.host == "vault.example.com"

    def test_returns_named_tuple(self) -> None:
        result = parse_uri("k8s://default")
        assert isinstance(result, ParsedURI)
        assert isinstance(result, tuple)

    def test_no_path(self) -> None:
        result = parse_uri("aws-sm://us-west-2")
        assert result.path == ""

    def test_empty_params(self) -> None:
        result = parse_uri("k8s://default")
        assert result.params == {}


class TestParseURIErrors:
    """Test error cases for URI parsing."""

    def test_empty_string(self) -> None:
        with pytest.raises(InvalidURIError, match="non-empty string"):
            parse_uri("")

    def test_none_input(self) -> None:
        with pytest.raises(InvalidURIError):
            parse_uri(None)  # type: ignore[arg-type]

    def test_missing_scheme(self) -> None:
        with pytest.raises(InvalidURIError, match="missing scheme"):
            parse_uri("vault.example.com:8200/secret")

    def test_unsupported_scheme(self) -> None:
        with pytest.raises(InvalidURIError, match="unsupported scheme"):
            parse_uri("redis://localhost:6379")

    def test_unsupported_scheme_message_lists_supported(self) -> None:
        with pytest.raises(InvalidURIError, match="must be one of"):
            parse_uri("ftp://example.com")


class TestSupportedSchemes:
    """Test the SUPPORTED_SCHEMES constant."""

    def test_all_eleven_schemes(self) -> None:
        assert len(SUPPORTED_SCHEMES) == 11

    def test_contains_all_backends(self) -> None:
        expected = {
            "vault", "infisical", "cyberark", "aws-sm", "gcp-sm",
            "azure-kv", "oci-vault", "k8s", "1password", "passbolt", "doppler",
        }
        assert SUPPORTED_SCHEMES == expected

    def test_is_frozenset(self) -> None:
        assert isinstance(SUPPORTED_SCHEMES, frozenset)
