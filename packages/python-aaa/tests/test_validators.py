"""Tests for penguin_aaa.hardening.validators."""

import pytest

from penguin_aaa.hardening.validators import (
    validate_algorithm,
    validate_https_url,
    validate_spiffe_id,
)

ALLOWED_ALGORITHMS = frozenset({"RS256", "RS384", "ES256", "PS256"})


class TestValidateHttpsUrl:
    def test_valid_https_url(self):
        validate_https_url("https://idp.example.com", "issuer")

    def test_https_with_path(self):
        validate_https_url("https://auth.example.com/oauth2", "redirect_url")

    def test_localhost_http_allowed(self):
        validate_https_url("http://localhost:8080", "issuer")

    def test_localhost_127_http_allowed(self):
        validate_https_url("http://127.0.0.1:8080", "issuer")

    def test_localhost_subdomain_allowed(self):
        validate_https_url("http://app.localhost:3000", "redirect_url")

    def test_http_non_localhost_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_https_url("http://idp.example.com", "issuer")

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_https_url("", "issuer")

    def test_whitespace_url_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_https_url("   ", "issuer")

    def test_malformed_url_rejected(self):
        with pytest.raises(ValueError, match="fully-qualified"):
            validate_https_url("not-a-url", "issuer")

    def test_field_name_in_error_message(self):
        with pytest.raises(ValueError, match="my_field"):
            validate_https_url("http://evil.com", "my_field")


class TestValidateSpiffeId:
    def test_valid_spiffe_id(self):
        validate_spiffe_id("spiffe://example.org/workload/api")

    def test_valid_spiffe_id_minimal(self):
        validate_spiffe_id("spiffe://trust-domain/service")

    def test_missing_scheme_rejected(self):
        with pytest.raises(ValueError, match="spiffe://"):
            validate_spiffe_id("https://example.org/workload")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_spiffe_id("")

    def test_whitespace_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_spiffe_id("   ")

    def test_missing_trust_domain_rejected(self):
        with pytest.raises(ValueError, match="trust domain"):
            validate_spiffe_id("spiffe:///no-trust-domain")

    def test_bare_scheme_rejected(self):
        with pytest.raises(ValueError, match="trust domain"):
            validate_spiffe_id("spiffe://")


class TestValidateAlgorithm:
    def test_allowed_algorithm_passes(self):
        validate_algorithm("RS256", ALLOWED_ALGORITHMS)

    def test_none_algorithm_rejected(self):
        with pytest.raises(ValueError, match="explicitly forbidden"):
            validate_algorithm("none", ALLOWED_ALGORITHMS)

    def test_hs256_rejected(self):
        with pytest.raises(ValueError, match="explicitly forbidden"):
            validate_algorithm("HS256", ALLOWED_ALGORITHMS)

    def test_unlisted_algorithm_rejected(self):
        with pytest.raises(ValueError, match="permitted set"):
            validate_algorithm("RS512", ALLOWED_ALGORITHMS)

    def test_all_allowed_algorithms_pass(self):
        for alg in ALLOWED_ALGORITHMS:
            validate_algorithm(alg, ALLOWED_ALGORITHMS)
