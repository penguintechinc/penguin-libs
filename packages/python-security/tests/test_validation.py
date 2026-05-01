"""
Comprehensive pytest tests for penguin-validation package.

Tests all validators with:
- Happy path (valid input)
- Rejection path (invalid input)
- Edge cases (boundaries, unicode, whitespace, None, etc.)
- All configurable options and combinations

Target: 95%+ line and branch coverage.
"""

from datetime import date, datetime, time
from re import Pattern

import pytest

from penguin_security.validation import (
    IsAlphanumeric,
    IsDate,
    IsDateInRange,
    IsDateTime,
    IsEmail,
    IsFloat,
    IsFloatInRange,
    IsHostname,
    IsIn,
    IsInt,
    IsIntInRange,
    IsIPAddress,
    IsLength,
    IsMatch,
    IsNegative,
    IsNotEmpty,
    IsPositive,
    IsSlug,
    IsStrongPassword,
    IsTime,
    IsURL,
    IsTrimmed,
    PasswordOptions,
    ValidationError,
    ValidationResult,
    chain,
)


# ============================================================================
# BASE VALIDATOR TESTS
# ============================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_success_creates_valid_result(self) -> None:
        result = ValidationResult.success("test")
        assert result.is_valid is True
        assert result.value == "test"
        assert result.error is None

    def test_failure_creates_invalid_result(self) -> None:
        result = ValidationResult.failure("error message")
        assert result.is_valid is False
        assert result.value is None
        assert result.error == "error message"

    def test_unwrap_returns_value_on_success(self) -> None:
        result = ValidationResult.success(42)
        assert result.unwrap() == 42

    def test_unwrap_raises_on_failure(self) -> None:
        result = ValidationResult.failure("invalid")
        with pytest.raises(ValidationError) as exc_info:
            result.unwrap()
        assert str(exc_info.value) == "invalid"

    def test_unwrap_raises_on_none_value(self) -> None:
        result = ValidationResult(is_valid=True, value=None, error=None)
        with pytest.raises(ValidationError):
            result.unwrap()

    def test_unwrap_or_returns_value_on_success(self) -> None:
        result = ValidationResult.success(42)
        assert result.unwrap_or(99) == 42

    def test_unwrap_or_returns_default_on_failure(self) -> None:
        result = ValidationResult.failure("error")
        assert result.unwrap_or(99) == 99

    def test_unwrap_or_returns_default_on_none_value(self) -> None:
        result = ValidationResult(is_valid=True, value=None, error=None)
        assert result.unwrap_or(99) == 99


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_error_without_field(self) -> None:
        err = ValidationError("invalid value")
        assert str(err) == "invalid value"
        assert err.field is None
        assert err.message == "invalid value"

    def test_error_with_field(self) -> None:
        err = ValidationError("invalid value", field="email")
        assert str(err) == "email: invalid value"
        assert err.field == "email"


class TestChainValidator:
    """Tests for chained validators."""

    def test_chain_single_validator(self) -> None:
        validator = chain(IsNotEmpty())
        result = validator("hello")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_chain_multiple_validators_all_pass(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsLength(3, 10),
        )
        result = validator("hello")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_chain_stops_on_first_failure(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsLength(3, 10),
            IsMatch(r"^[a-z]+$"),
        )
        result = validator("hi")  # Fails length check
        assert result.is_valid is False
        assert "at least 3" in result.error.lower()

    def test_chain_and_then_method(self) -> None:
        validator = IsNotEmpty().and_then(IsLength(3, 10))
        result = validator("hello")
        assert result.is_valid is True

    def test_chain_passes_transformed_value(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsTrimmed(),
        )
        result = validator("  hello  ")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_chain_empty_validators_passes(self) -> None:
        validator = chain()
        result = validator("anything")
        assert result.is_valid is True


# ============================================================================
# STRING VALIDATORS
# ============================================================================


class TestIsNotEmpty:
    """Tests for IsNotEmpty validator."""

    def test_valid_non_empty_string(self) -> None:
        validator = IsNotEmpty()
        result = validator("hello")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_invalid_empty_string(self) -> None:
        validator = IsNotEmpty()
        result = validator("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_invalid_whitespace_only(self) -> None:
        validator = IsNotEmpty()
        result = validator("   ")
        assert result.is_valid is False

    def test_invalid_tabs_and_newlines(self) -> None:
        validator = IsNotEmpty()
        result = validator("\t\n\r")
        assert result.is_valid is False

    def test_strips_whitespace(self) -> None:
        validator = IsNotEmpty()
        result = validator("  hello  ")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_invalid_non_string(self) -> None:
        validator = IsNotEmpty()
        result = validator(42)  # type: ignore
        assert result.is_valid is False
        assert "string" in result.error.lower()

    def test_custom_error_message(self) -> None:
        validator = IsNotEmpty(error_message="Cannot be blank")
        result = validator("")
        assert result.error == "Cannot be blank"

    def test_unicode_non_empty(self) -> None:
        validator = IsNotEmpty()
        result = validator("你好")
        assert result.is_valid is True


class TestIsLength:
    """Tests for IsLength validator."""

    def test_valid_length_within_range(self) -> None:
        validator = IsLength(min_length=2, max_length=5)
        result = validator("hello")
        assert result.is_valid is True

    def test_invalid_too_short(self) -> None:
        validator = IsLength(min_length=3)
        result = validator("hi")
        assert result.is_valid is False
        assert "at least 3" in result.error.lower()

    def test_invalid_too_long(self) -> None:
        validator = IsLength(max_length=5)
        result = validator("hello world")
        assert result.is_valid is False
        assert "at most 5" in result.error.lower()

    def test_boundary_exact_min(self) -> None:
        validator = IsLength(min_length=5)
        result = validator("hello")
        assert result.is_valid is True

    def test_boundary_exact_max(self) -> None:
        validator = IsLength(max_length=5)
        result = validator("hello")
        assert result.is_valid is True

    def test_boundary_one_below_min(self) -> None:
        validator = IsLength(min_length=5)
        result = validator("hell")
        assert result.is_valid is False

    def test_boundary_one_over_max(self) -> None:
        validator = IsLength(max_length=5)
        result = validator("helloo")
        assert result.is_valid is False

    def test_zero_min_length(self) -> None:
        validator = IsLength(min_length=0, max_length=5)
        result = validator("")
        assert result.is_valid is True

    def test_no_max_length(self) -> None:
        validator = IsLength(min_length=3)
        result = validator("x" * 1000)
        assert result.is_valid is True

    def test_custom_error_message(self) -> None:
        validator = IsLength(min_length=5, error_message="Must be 5+ chars")
        result = validator("hi")
        assert result.error == "Must be 5+ chars"

    def test_non_string_input(self) -> None:
        validator = IsLength(min_length=3)
        result = validator(42)  # type: ignore
        assert result.is_valid is False
        assert "string" in result.error.lower()


class TestIsMatch:
    """Tests for IsMatch validator."""

    def test_valid_regex_match(self) -> None:
        validator = IsMatch(r"^[A-Z]{2}\d{4}$")
        result = validator("AB1234")
        assert result.is_valid is True

    def test_invalid_regex_no_match(self) -> None:
        validator = IsMatch(r"^[A-Z]{2}\d{4}$")
        result = validator("ab1234")
        assert result.is_valid is False

    def test_compiled_pattern(self) -> None:
        import re

        pattern = re.compile(r"^[a-z]+$")
        validator = IsMatch(pattern)
        result = validator("hello")
        assert result.is_valid is True

    def test_regex_with_flags(self) -> None:
        import re

        validator = IsMatch(r"^hello$", flags=re.IGNORECASE)
        result = validator("HELLO")
        assert result.is_valid is True

    def test_custom_error_message(self) -> None:
        validator = IsMatch(r"^\d+$", error_message="Must be digits only")
        result = validator("abc")
        assert result.error == "Must be digits only"

    def test_non_string_input(self) -> None:
        validator = IsMatch(r"^test$")
        result = validator(42)  # type: ignore
        assert result.is_valid is False


class TestIsAlphanumeric:
    """Tests for IsAlphanumeric validator."""

    def test_valid_letters_and_numbers(self) -> None:
        validator = IsAlphanumeric()
        result = validator("Hello123")
        assert result.is_valid is True

    def test_valid_letters_only(self) -> None:
        validator = IsAlphanumeric()
        result = validator("Hello")
        assert result.is_valid is True

    def test_valid_numbers_only(self) -> None:
        validator = IsAlphanumeric()
        result = validator("123")
        assert result.is_valid is True

    def test_invalid_with_special_chars(self) -> None:
        validator = IsAlphanumeric()
        result = validator("Hello!")
        assert result.is_valid is False

    def test_invalid_with_spaces(self) -> None:
        validator = IsAlphanumeric()
        result = validator("Hello World")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsAlphanumeric()
        result = validator("")
        assert result.is_valid is False

    def test_allow_underscore(self) -> None:
        validator = IsAlphanumeric(allow_underscore=True)
        result = validator("hello_world")
        assert result.is_valid is True

    def test_allow_dash(self) -> None:
        validator = IsAlphanumeric(allow_dash=True)
        result = validator("hello-world")
        assert result.is_valid is True

    def test_allow_both(self) -> None:
        validator = IsAlphanumeric(allow_underscore=True, allow_dash=True)
        result = validator("hello_world-test")
        assert result.is_valid is True

    def test_dash_not_allowed_by_default(self) -> None:
        validator = IsAlphanumeric()
        result = validator("hello-world")
        assert result.is_valid is False

    def test_non_string_input(self) -> None:
        validator = IsAlphanumeric()
        result = validator(42)  # type: ignore
        assert result.is_valid is False


class TestIsSlug:
    """Tests for IsSlug validator."""

    def test_valid_slug(self) -> None:
        validator = IsSlug()
        result = validator("my-blog-post")
        assert result.is_valid is True

    def test_valid_slug_numbers(self) -> None:
        validator = IsSlug()
        result = validator("post-123")
        assert result.is_valid is True

    def test_valid_slug_single_word(self) -> None:
        validator = IsSlug()
        result = validator("hello")
        assert result.is_valid is True

    def test_invalid_uppercase(self) -> None:
        validator = IsSlug()
        result = validator("My-Blog-Post")
        assert result.is_valid is False

    def test_invalid_spaces(self) -> None:
        validator = IsSlug()
        result = validator("my blog post")
        assert result.is_valid is False

    def test_invalid_starts_with_dash(self) -> None:
        validator = IsSlug()
        result = validator("-my-post")
        assert result.is_valid is False

    def test_invalid_ends_with_dash(self) -> None:
        validator = IsSlug()
        result = validator("my-post-")
        assert result.is_valid is False

    def test_invalid_consecutive_dashes(self) -> None:
        validator = IsSlug()
        result = validator("my--post")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsSlug()
        result = validator("")
        assert result.is_valid is False

    def test_invalid_special_chars(self) -> None:
        validator = IsSlug()
        result = validator("my_post")
        assert result.is_valid is False


class TestIsIn:
    """Tests for IsIn validator."""

    def test_valid_value_in_list(self) -> None:
        validator = IsIn(["admin", "user", "guest"])
        result = validator("admin")
        assert result.is_valid is True

    def test_invalid_value_not_in_list(self) -> None:
        validator = IsIn(["admin", "user", "guest"])
        result = validator("superuser")
        assert result.is_valid is False

    def test_case_sensitive_by_default(self) -> None:
        validator = IsIn(["admin", "user"])
        result = validator("ADMIN")
        assert result.is_valid is False

    def test_case_insensitive_option(self) -> None:
        validator = IsIn(["admin", "user"], case_sensitive=False)
        result = validator("ADMIN")
        assert result.is_valid is True

    def test_case_insensitive_mixed_case(self) -> None:
        validator = IsIn(["admin", "user"], case_sensitive=False)
        result = validator("AdMiN")
        assert result.is_valid is True

    def test_custom_error_message(self) -> None:
        validator = IsIn(["a", "b"], error_message="Must be a or b")
        result = validator("c")
        assert result.error == "Must be a or b"

    def test_non_string_input(self) -> None:
        validator = IsIn(["admin"])
        result = validator(42)  # type: ignore
        assert result.is_valid is False

    def test_empty_options_list(self) -> None:
        validator = IsIn([])
        result = validator("anything")
        assert result.is_valid is False


class TestIsTrimmed:
    """Tests for IsTrimmed validator."""

    def test_trims_leading_whitespace(self) -> None:
        validator = IsTrimmed()
        result = validator("   hello")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_trims_trailing_whitespace(self) -> None:
        validator = IsTrimmed()
        result = validator("hello   ")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_trims_both_sides(self) -> None:
        validator = IsTrimmed()
        result = validator("   hello   ")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_trims_tabs_and_newlines(self) -> None:
        validator = IsTrimmed()
        result = validator("\t\nhello\n\t")
        assert result.is_valid is True
        assert result.value == "hello"

    def test_empty_after_trim_fails(self) -> None:
        validator = IsTrimmed()
        result = validator("   ")
        assert result.is_valid is False

    def test_empty_after_trim_allowed(self) -> None:
        validator = IsTrimmed(allow_empty=True)
        result = validator("   ")
        assert result.is_valid is True
        assert result.value == ""

    def test_non_string_input(self) -> None:
        validator = IsTrimmed()
        result = validator(42)  # type: ignore
        assert result.is_valid is False


# ============================================================================
# NUMERIC VALIDATORS
# ============================================================================


class TestIsInt:
    """Tests for IsInt validator."""

    def test_valid_integer(self) -> None:
        validator = IsInt()
        result = validator(42)
        assert result.is_valid is True
        assert result.value == 42

    def test_valid_integer_string(self) -> None:
        validator = IsInt()
        result = validator("42")
        assert result.is_valid is True
        assert result.value == 42

    def test_valid_float_as_integer(self) -> None:
        validator = IsInt()
        result = validator(42.0)
        assert result.is_valid is True
        assert result.value == 42

    def test_invalid_non_integer_float(self) -> None:
        validator = IsInt()
        result = validator(3.14)
        assert result.is_valid is False

    def test_invalid_float_string(self) -> None:
        validator = IsInt()
        result = validator("3.14")
        assert result.is_valid is False

    def test_invalid_string(self) -> None:
        validator = IsInt()
        result = validator("abc")
        assert result.is_valid is False

    def test_invalid_bool(self) -> None:
        validator = IsInt()
        result = validator(True)  # type: ignore
        assert result.is_valid is False

    def test_negative_integer(self) -> None:
        validator = IsInt()
        result = validator(-42)
        assert result.is_valid is True

    def test_zero(self) -> None:
        validator = IsInt()
        result = validator(0)
        assert result.is_valid is True

    def test_scientific_notation_string_invalid(self) -> None:
        validator = IsInt()
        result = validator("1e5")
        assert result.is_valid is False


class TestIsFloat:
    """Tests for IsFloat validator."""

    def test_valid_float(self) -> None:
        validator = IsFloat()
        result = validator(3.14)
        assert result.is_valid is True
        assert result.value == 3.14

    def test_valid_integer_as_float(self) -> None:
        validator = IsFloat()
        result = validator(42)
        assert result.is_valid is True
        assert result.value == 42.0

    def test_valid_float_string(self) -> None:
        validator = IsFloat()
        result = validator("3.14")
        assert result.is_valid is True
        assert result.value == 3.14

    def test_valid_scientific_notation(self) -> None:
        validator = IsFloat()
        result = validator("1.5e2")
        assert result.is_valid is True

    def test_invalid_string(self) -> None:
        validator = IsFloat()
        result = validator("abc")
        assert result.is_valid is False

    def test_invalid_bool(self) -> None:
        validator = IsFloat()
        result = validator(True)  # type: ignore
        assert result.is_valid is False

    def test_negative_float(self) -> None:
        validator = IsFloat()
        result = validator(-3.14)
        assert result.is_valid is True

    def test_zero_float(self) -> None:
        validator = IsFloat()
        result = validator(0.0)
        assert result.is_valid is True


class TestIsIntInRange:
    """Tests for IsIntInRange validator."""

    def test_valid_within_range(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator(50)
        assert result.is_valid is True

    def test_boundary_min_inclusive(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator(1)
        assert result.is_valid is True

    def test_boundary_max_inclusive(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator(100)
        assert result.is_valid is True

    def test_below_min(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator(0)
        assert result.is_valid is False

    def test_above_max(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator(101)
        assert result.is_valid is False

    def test_no_min_constraint(self) -> None:
        validator = IsIntInRange(max_value=100)
        result = validator(-9999)
        assert result.is_valid is True

    def test_no_max_constraint(self) -> None:
        validator = IsIntInRange(min_value=1)
        result = validator(999999)
        assert result.is_valid is True

    def test_string_conversion(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator("50")
        assert result.is_valid is True

    def test_invalid_string(self) -> None:
        validator = IsIntInRange(min_value=1, max_value=100)
        result = validator("abc")
        assert result.is_valid is False


class TestIsFloatInRange:
    """Tests for IsFloatInRange validator."""

    def test_valid_within_range(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(0.5)
        assert result.is_valid is True

    def test_boundary_min_inclusive(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(0.0)
        assert result.is_valid is True

    def test_boundary_max_inclusive(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(1.0)
        assert result.is_valid is True

    def test_below_min(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(-0.1)
        assert result.is_valid is False

    def test_above_max(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(1.1)
        assert result.is_valid is False

    def test_string_conversion(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator("0.5")
        assert result.is_valid is True


class TestIsPositive:
    """Tests for IsPositive validator."""

    def test_valid_positive(self) -> None:
        validator = IsPositive()
        result = validator(5)
        assert result.is_valid is True

    def test_invalid_negative(self) -> None:
        validator = IsPositive()
        result = validator(-5)
        assert result.is_valid is False

    def test_invalid_zero(self) -> None:
        validator = IsPositive()
        result = validator(0)
        assert result.is_valid is False

    def test_allow_zero(self) -> None:
        validator = IsPositive(allow_zero=True)
        result = validator(0)
        assert result.is_valid is True

    def test_allow_zero_positive_still_valid(self) -> None:
        validator = IsPositive(allow_zero=True)
        result = validator(5)
        assert result.is_valid is True

    def test_allow_zero_negative_invalid(self) -> None:
        validator = IsPositive(allow_zero=True)
        result = validator(-5)
        assert result.is_valid is False

    def test_positive_float(self) -> None:
        validator = IsPositive()
        result = validator(3.14)
        assert result.is_valid is True


class TestIsNegative:
    """Tests for IsNegative validator."""

    def test_valid_negative(self) -> None:
        validator = IsNegative()
        result = validator(-5)
        assert result.is_valid is True

    def test_invalid_positive(self) -> None:
        validator = IsNegative()
        result = validator(5)
        assert result.is_valid is False

    def test_invalid_zero(self) -> None:
        validator = IsNegative()
        result = validator(0)
        assert result.is_valid is False

    def test_allow_zero(self) -> None:
        validator = IsNegative(allow_zero=True)
        result = validator(0)
        assert result.is_valid is True

    def test_allow_zero_negative_still_valid(self) -> None:
        validator = IsNegative(allow_zero=True)
        result = validator(-5)
        assert result.is_valid is True

    def test_allow_zero_positive_invalid(self) -> None:
        validator = IsNegative(allow_zero=True)
        result = validator(5)
        assert result.is_valid is False

    def test_negative_float(self) -> None:
        validator = IsNegative()
        result = validator(-3.14)
        assert result.is_valid is True


# ============================================================================
# NETWORK VALIDATORS
# ============================================================================


class TestIsEmail:
    """Tests for IsEmail validator."""

    def test_valid_standard_email(self) -> None:
        validator = IsEmail()
        result = validator("user@example.com")
        assert result.is_valid is True

    def test_valid_email_with_subdomain(self) -> None:
        validator = IsEmail()
        result = validator("user@mail.example.com")
        assert result.is_valid is True

    def test_valid_email_with_dots(self) -> None:
        validator = IsEmail()
        result = validator("john.doe@example.com")
        assert result.is_valid is True

    def test_valid_email_with_numbers(self) -> None:
        validator = IsEmail()
        result = validator("user123@example.com")
        assert result.is_valid is True

    def test_valid_email_with_special_chars(self) -> None:
        validator = IsEmail()
        result = validator("user+tag@example.com")
        assert result.is_valid is True

    def test_normalize_to_lowercase(self) -> None:
        validator = IsEmail(normalize=True)
        result = validator("User@Example.COM")
        assert result.is_valid is True
        assert result.value == "user@example.com"

    def test_no_normalization(self) -> None:
        validator = IsEmail(normalize=False)
        result = validator("User@Example.COM")
        assert result.is_valid is True
        assert result.value == "User@Example.COM"

    def test_invalid_no_at_sign(self) -> None:
        validator = IsEmail()
        result = validator("userexample.com")
        assert result.is_valid is False

    def test_invalid_no_tld(self) -> None:
        validator = IsEmail()
        result = validator("user@example")
        assert result.is_valid is False

    def test_invalid_multiple_at_signs(self) -> None:
        validator = IsEmail()
        result = validator("user@@example.com")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsEmail()
        result = validator("")
        assert result.is_valid is False

    def test_invalid_whitespace_only(self) -> None:
        validator = IsEmail()
        result = validator("   ")
        assert result.is_valid is False

    def test_invalid_local_part_too_long(self) -> None:
        validator = IsEmail()
        result = validator("a" * 65 + "@example.com")
        assert result.is_valid is False

    def test_invalid_total_length_too_long(self) -> None:
        validator = IsEmail()
        result = validator("a" * 250 + "@example.com")
        assert result.is_valid is False

    def test_trims_whitespace(self) -> None:
        validator = IsEmail()
        result = validator("  user@example.com  ")
        assert result.is_valid is True


class TestIsURL:
    """Tests for IsURL validator."""

    def test_valid_https_url(self) -> None:
        validator = IsURL()
        result = validator("https://example.com")
        assert result.is_valid is True

    def test_valid_http_url(self) -> None:
        validator = IsURL()
        result = validator("http://example.com")
        assert result.is_valid is True

    def test_valid_url_with_path(self) -> None:
        validator = IsURL()
        result = validator("https://example.com/path/to/resource")
        assert result.is_valid is True

    def test_valid_url_with_query_params(self) -> None:
        validator = IsURL()
        result = validator("https://example.com/path?key=value")
        assert result.is_valid is True

    def test_valid_url_with_fragment(self) -> None:
        validator = IsURL()
        result = validator("https://example.com/path#section")
        assert result.is_valid is True

    def test_valid_url_with_port(self) -> None:
        validator = IsURL()
        result = validator("https://example.com:8080/path")
        assert result.is_valid is True

    def test_valid_url_with_subdomain(self) -> None:
        validator = IsURL()
        result = validator("https://api.example.com")
        assert result.is_valid is True

    def test_invalid_no_scheme(self) -> None:
        validator = IsURL()
        result = validator("example.com")
        assert result.is_valid is False

    def test_invalid_unsupported_scheme(self) -> None:
        validator = IsURL()
        result = validator("ftp://example.com")
        assert result.is_valid is False

    def test_custom_allowed_schemes(self) -> None:
        validator = IsURL(allowed_schemes=["ftp", "sftp"])
        result = validator("ftp://example.com")
        assert result.is_valid is True

    def test_custom_allowed_schemes_https_not_allowed(self) -> None:
        validator = IsURL(allowed_schemes=["ftp"])
        result = validator("https://example.com")
        assert result.is_valid is False

    def test_invalid_no_hostname(self) -> None:
        validator = IsURL()
        result = validator("https://")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsURL()
        result = validator("")
        assert result.is_valid is False

    def test_localhost_without_tld(self) -> None:
        validator = IsURL()
        result = validator("http://localhost")
        assert result.is_valid is True

    def test_require_tld_localhost_allowed(self) -> None:
        validator = IsURL(require_tld=True)
        result = validator("http://localhost")
        assert result.is_valid is True

    def test_no_tld_requirement(self) -> None:
        validator = IsURL(require_tld=False)
        result = validator("http://server")
        assert result.is_valid is True


class TestIsIPAddress:
    """Tests for IsIPAddress validator."""

    def test_valid_ipv4(self) -> None:
        validator = IsIPAddress()
        result = validator("192.168.1.1")
        assert result.is_valid is True

    def test_valid_ipv4_localhost(self) -> None:
        validator = IsIPAddress()
        result = validator("127.0.0.1")
        assert result.is_valid is True

    def test_valid_ipv4_zeros(self) -> None:
        validator = IsIPAddress()
        result = validator("0.0.0.0")
        assert result.is_valid is True

    def test_valid_ipv4_broadcast(self) -> None:
        validator = IsIPAddress()
        result = validator("255.255.255.255")
        assert result.is_valid is True

    def test_valid_ipv6(self) -> None:
        validator = IsIPAddress()
        result = validator("::1")
        assert result.is_valid is True

    def test_valid_ipv6_full(self) -> None:
        validator = IsIPAddress()
        result = validator("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert result.is_valid is True

    def test_ipv4_only_rejects_ipv6(self) -> None:
        validator = IsIPAddress(version=4)
        result = validator("::1")
        assert result.is_valid is False

    def test_ipv6_only_rejects_ipv4(self) -> None:
        validator = IsIPAddress(version=6)
        result = validator("192.168.1.1")
        assert result.is_valid is False

    def test_invalid_malformed_ipv4(self) -> None:
        validator = IsIPAddress()
        result = validator("256.256.256.256")
        assert result.is_valid is False

    def test_invalid_string(self) -> None:
        validator = IsIPAddress()
        result = validator("not-an-ip")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsIPAddress()
        result = validator("")
        assert result.is_valid is False

    def test_version_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            IsIPAddress(version=5)  # type: ignore

    def test_trims_whitespace(self) -> None:
        validator = IsIPAddress()
        result = validator("  192.168.1.1  ")
        assert result.is_valid is True


class TestIsHostname:
    """Tests for IsHostname validator."""

    def test_valid_hostname_single_label(self) -> None:
        validator = IsHostname()
        result = validator("localhost")
        assert result.is_valid is True

    def test_valid_hostname_with_tld(self) -> None:
        validator = IsHostname()
        result = validator("example.com")
        assert result.is_valid is True

    def test_valid_hostname_multiple_labels(self) -> None:
        validator = IsHostname()
        result = validator("mail.example.com")
        assert result.is_valid is True

    def test_valid_hostname_with_dash(self) -> None:
        validator = IsHostname()
        result = validator("my-server")
        assert result.is_valid is True

    def test_valid_hostname_with_numbers(self) -> None:
        validator = IsHostname()
        result = validator("server1.example.com")
        assert result.is_valid is True

    def test_invalid_starts_with_dash(self) -> None:
        validator = IsHostname()
        result = validator("-invalid")
        assert result.is_valid is False

    def test_invalid_ends_with_dash(self) -> None:
        validator = IsHostname()
        result = validator("invalid-")
        assert result.is_valid is False

    def test_invalid_consecutive_dots(self) -> None:
        validator = IsHostname()
        result = validator("invalid..com")
        assert result.is_valid is False

    def test_invalid_label_starts_with_dash(self) -> None:
        validator = IsHostname()
        result = validator("invalid.-com")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsHostname()
        result = validator("")
        assert result.is_valid is False

    def test_allow_ip_as_hostname(self) -> None:
        validator = IsHostname(allow_ip=True)
        result = validator("192.168.1.1")
        assert result.is_valid is True

    def test_require_tld(self) -> None:
        validator = IsHostname(require_tld=True)
        result = validator("localhost")
        assert result.is_valid is False

    def test_require_tld_with_dot(self) -> None:
        validator = IsHostname(require_tld=True)
        result = validator("localhost.local")
        assert result.is_valid is True

    def test_hostname_too_long(self) -> None:
        validator = IsHostname()
        result = validator("a" * 254)
        assert result.is_valid is False

    def test_trims_whitespace(self) -> None:
        validator = IsHostname()
        result = validator("  example.com  ")
        assert result.is_valid is True


# ============================================================================
# DATETIME VALIDATORS
# ============================================================================


class TestIsDate:
    """Tests for IsDate validator."""

    def test_valid_date_string_iso(self) -> None:
        validator = IsDate()
        result = validator("2024-01-15")
        assert result.is_valid is True
        assert result.value == date(2024, 1, 15)

    def test_valid_date_object(self) -> None:
        validator = IsDate()
        result = validator(date(2024, 1, 15))
        assert result.is_valid is True
        assert result.value == date(2024, 1, 15)

    def test_valid_datetime_extracts_date(self) -> None:
        validator = IsDate()
        result = validator(datetime(2024, 1, 15, 14, 30, 0))
        assert result.is_valid is True
        assert result.value == date(2024, 1, 15)

    def test_custom_format(self) -> None:
        validator = IsDate(format="%d/%m/%Y")
        result = validator("15/01/2024")
        assert result.is_valid is True

    def test_invalid_wrong_format(self) -> None:
        validator = IsDate()
        result = validator("15/01/2024")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsDate()
        result = validator("")
        assert result.is_valid is False

    def test_invalid_invalid_date(self) -> None:
        validator = IsDate()
        result = validator("2024-13-01")
        assert result.is_valid is False

    def test_trims_whitespace(self) -> None:
        validator = IsDate()
        result = validator("  2024-01-15  ")
        assert result.is_valid is True


class TestIsDateTime:
    """Tests for IsDateTime validator."""

    def test_valid_datetime_string_iso(self) -> None:
        validator = IsDateTime()
        result = validator("2024-01-15T14:30:00")
        assert result.is_valid is True
        assert result.value == datetime(2024, 1, 15, 14, 30, 0)

    def test_valid_datetime_object(self) -> None:
        validator = IsDateTime()
        dt = datetime(2024, 1, 15, 14, 30, 0)
        result = validator(dt)
        assert result.is_valid is True
        assert result.value == dt

    def test_custom_format(self) -> None:
        validator = IsDateTime(format="%Y-%m-%d %H:%M")
        result = validator("2024-01-15 14:30")
        assert result.is_valid is True

    def test_invalid_date_only(self) -> None:
        validator = IsDateTime()
        result = validator("2024-01-15")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsDateTime()
        result = validator("")
        assert result.is_valid is False

    def test_trims_whitespace(self) -> None:
        validator = IsDateTime()
        result = validator("  2024-01-15T14:30:00  ")
        assert result.is_valid is True


class TestIsTime:
    """Tests for IsTime validator."""

    def test_valid_time_string(self) -> None:
        validator = IsTime()
        result = validator("14:30:00")
        assert result.is_valid is True
        assert result.value == time(14, 30, 0)

    def test_valid_time_object(self) -> None:
        validator = IsTime()
        t = time(14, 30, 0)
        result = validator(t)
        assert result.is_valid is True
        assert result.value == t

    def test_valid_time_from_datetime(self) -> None:
        validator = IsTime()
        result = validator(datetime(2024, 1, 15, 14, 30, 0))
        assert result.is_valid is True
        assert result.value == time(14, 30, 0)

    def test_custom_format(self) -> None:
        validator = IsTime(format="%H:%M")
        result = validator("14:30")
        assert result.is_valid is True

    def test_invalid_wrong_format(self) -> None:
        validator = IsTime()
        result = validator("14:30")
        assert result.is_valid is False

    def test_invalid_empty_string(self) -> None:
        validator = IsTime()
        result = validator("")
        assert result.is_valid is False

    def test_trims_whitespace(self) -> None:
        validator = IsTime()
        result = validator("  14:30:00  ")
        assert result.is_valid is True


class TestIsDateInRange:
    """Tests for IsDateInRange validator."""

    def test_valid_within_range(self) -> None:
        validator = IsDateInRange(
            min_date=date(2024, 1, 1),
            max_date=date(2024, 12, 31),
        )
        result = validator("2024-06-15")
        assert result.is_valid is True

    def test_boundary_min_inclusive(self) -> None:
        validator = IsDateInRange(min_date=date(2024, 1, 1))
        result = validator("2024-01-01")
        assert result.is_valid is True

    def test_boundary_max_inclusive(self) -> None:
        validator = IsDateInRange(max_date=date(2024, 12, 31))
        result = validator("2024-12-31")
        assert result.is_valid is True

    def test_before_min(self) -> None:
        validator = IsDateInRange(min_date=date(2024, 1, 1))
        result = validator("2023-12-31")
        assert result.is_valid is False

    def test_after_max(self) -> None:
        validator = IsDateInRange(max_date=date(2024, 12, 31))
        result = validator("2025-01-01")
        assert result.is_valid is False

    def test_date_object_input(self) -> None:
        validator = IsDateInRange(min_date=date(2024, 1, 1))
        result = validator(date(2024, 6, 15))
        assert result.is_valid is True

    def test_custom_format(self) -> None:
        validator = IsDateInRange(
            min_date=date(2024, 1, 1),
            format="%d/%m/%Y",
        )
        result = validator("15/06/2024")
        assert result.is_valid is True


# ============================================================================
# PASSWORD VALIDATORS
# ============================================================================


class TestPasswordOptions:
    """Tests for PasswordOptions configuration."""

    def test_default_options(self) -> None:
        opts = PasswordOptions()
        assert opts.min_length == 8
        assert opts.max_length == 128
        assert opts.require_uppercase is True
        assert opts.require_lowercase is True
        assert opts.require_digit is True
        assert opts.require_special is True
        assert opts.disallow_spaces is True

    def test_weak_preset(self) -> None:
        opts = PasswordOptions.weak()
        assert opts.min_length == 6
        assert opts.require_uppercase is False
        assert opts.require_lowercase is False
        assert opts.require_digit is False
        assert opts.require_special is False

    def test_moderate_preset(self) -> None:
        opts = PasswordOptions.moderate()
        assert opts.min_length == 8
        assert opts.require_uppercase is True
        assert opts.require_lowercase is True
        assert opts.require_digit is True
        assert opts.require_special is False

    def test_strong_preset(self) -> None:
        opts = PasswordOptions.strong()
        assert opts.min_length == 12
        assert opts.require_special is True

    def test_enterprise_preset(self) -> None:
        opts = PasswordOptions.enterprise()
        assert opts.min_length == 16
        assert opts.max_length == 256


class TestIsStrongPassword:
    """Tests for IsStrongPassword validator."""

    def test_valid_strong_password(self) -> None:
        validator = IsStrongPassword()
        result = validator("MyP@ssw0rd!")
        assert result.is_valid is True

    def test_invalid_too_short(self) -> None:
        validator = IsStrongPassword()
        result = validator("Short1!")
        assert result.is_valid is False

    def test_invalid_too_long(self) -> None:
        validator = IsStrongPassword(max_length=10)
        result = validator("VeryLongPassword123!")
        assert result.is_valid is False

    def test_invalid_no_uppercase(self) -> None:
        validator = IsStrongPassword()
        result = validator("myp@ssw0rd!")
        assert result.is_valid is False

    def test_invalid_no_lowercase(self) -> None:
        validator = IsStrongPassword()
        result = validator("MYP@SSW0RD!")
        assert result.is_valid is False

    def test_invalid_no_digit(self) -> None:
        validator = IsStrongPassword()
        result = validator("MyP@ssword!")
        assert result.is_valid is False

    def test_invalid_no_special(self) -> None:
        validator = IsStrongPassword()
        result = validator("MyPassword0")
        assert result.is_valid is False

    def test_invalid_contains_space(self) -> None:
        validator = IsStrongPassword()
        result = validator("My P@ssw0rd!")
        assert result.is_valid is False

    def test_allow_spaces(self) -> None:
        validator = IsStrongPassword(disallow_spaces=False)
        result = validator("My P@ssw0rd!")
        assert result.is_valid is True

    def test_custom_special_chars(self) -> None:
        validator = IsStrongPassword(special_chars="~!@")
        result = validator("MyPassword1~")
        assert result.is_valid is True

    def test_weak_preset(self) -> None:
        validator = IsStrongPassword(options=PasswordOptions.weak())
        result = validator("simple")
        assert result.is_valid is True

    def test_strong_preset(self) -> None:
        validator = IsStrongPassword(options=PasswordOptions.strong())
        result = validator("MyP@ssw0rd!")
        assert result.is_valid is False  # min_length=12

    def test_enterprise_preset(self) -> None:
        validator = IsStrongPassword(options=PasswordOptions.enterprise())
        result = validator("MyP@ssw0rdVeryLong123")
        assert result.is_valid is True

    def test_custom_error_message(self) -> None:
        validator = IsStrongPassword(error_message="Password not strong enough")
        result = validator("weak")
        assert result.error == "Password not strong enough"

    def test_multiple_errors_joined(self) -> None:
        validator = IsStrongPassword()
        result = validator("a")  # violates multiple constraints
        assert result.is_valid is False
        assert ";" in result.error  # Multiple errors joined with ;

    def test_kwargs_override_defaults(self) -> None:
        validator = IsStrongPassword(min_length=12, require_special=False)
        result = validator("MyPassword123")
        assert result.is_valid is True

    def test_non_string_input(self) -> None:
        validator = IsStrongPassword()
        result = validator(12345)  # type: ignore
        assert result.is_valid is False

    def test_get_strength_score_weak(self) -> None:
        validator = IsStrongPassword()
        score = validator.get_strength_score("a")
        assert 0 <= score <= 100
        assert score < 50

    def test_get_strength_score_strong(self) -> None:
        validator = IsStrongPassword()
        score = validator.get_strength_score("MyVeryStrongP@ssw0rd!")
        assert 50 <= score <= 100

    def test_strength_score_length_contribution(self) -> None:
        validator = IsStrongPassword()
        short = validator.get_strength_score("Aa1@")  # Minimal valid, very short
        long = validator.get_strength_score("VeryLongPasswordWithM@ny123CharsHere")  # Very long
        assert long > short

    def test_strength_score_variety_contribution(self) -> None:
        validator = IsStrongPassword()
        no_special = validator.get_strength_score("MyPassword0")
        with_special = validator.get_strength_score("MyP@ssw0rd")
        assert with_special > no_special

    def test_strength_score_no_common_patterns(self) -> None:
        validator = IsStrongPassword()
        with_pattern = validator.get_strength_score("Password123")
        without_pattern = validator.get_strength_score("Zx@kl9Qw")
        assert without_pattern >= with_pattern

    def test_strength_score_max_100(self) -> None:
        validator = IsStrongPassword()
        score = validator.get_strength_score("X" * 200 + "y@1Z")  # Very long password
        assert score <= 100


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestValidatorChaining:
    """Integration tests for chained validators."""

    def test_email_validation_chain(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsLength(5, 254),
            IsEmail(),
        )
        result = validator("user@example.com")
        assert result.is_valid is True

    def test_password_validation_chain(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsTrimmed(),
            IsStrongPassword(),
        )
        result = validator("  MyP@ssw0rd!  ")
        assert result.is_valid is True
        assert result.value == "MyP@ssw0rd!"

    def test_url_validation_chain(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsURL(),
        )
        result = validator("https://example.com/path")
        assert result.is_valid is True

    def test_date_range_validation(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsDateInRange(
                min_date=date(2024, 1, 1),
                max_date=date(2024, 12, 31),
            ),
        )
        result = validator("2024-06-15")
        assert result.is_valid is True

    def test_numeric_range_validation(self) -> None:
        validator = chain(
            IsInt(),
            IsIntInRange(min_value=1, max_value=100),
        )
        result = validator("50")
        assert result.is_valid is True

    def test_slug_creation_chain(self) -> None:
        validator = chain(
            IsNotEmpty(),
            IsLength(3, 50),
            IsSlug(),
        )
        result = validator("my-blog-post")
        assert result.is_valid is True


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_unicode_handling_string_validators(self) -> None:
        validator = IsNotEmpty()
        result = validator("你好世界")
        assert result.is_valid is True

    def test_unicode_email(self) -> None:
        validator = IsEmail()
        result = validator("用户@example.com")
        assert result.is_valid is False  # Standard email regex doesn't support unicode

    def test_very_long_string(self) -> None:
        validator = IsLength(max_length=1000)
        result = validator("x" * 500)
        assert result.is_valid is True

    def test_very_long_string_exceeds_max(self) -> None:
        validator = IsLength(max_length=100)
        result = validator("x" * 101)
        assert result.is_valid is False

    def test_negative_zero_float(self) -> None:
        validator = IsPositive(allow_zero=True)
        result = validator(-0.0)
        assert result.is_valid is True

    def test_float_precision_boundaries(self) -> None:
        validator = IsFloatInRange(min_value=0.0, max_value=1.0)
        result = validator(0.9999999999)
        assert result.is_valid is True

    def test_leap_year_date(self) -> None:
        validator = IsDate()
        result = validator("2024-02-29")
        assert result.is_valid is True

    def test_non_leap_year_feb_29(self) -> None:
        validator = IsDate()
        result = validator("2023-02-29")
        assert result.is_valid is False

    def test_midnight_time(self) -> None:
        validator = IsTime()
        result = validator("00:00:00")
        assert result.is_valid is True

    def test_end_of_day_time(self) -> None:
        validator = IsTime()
        result = validator("23:59:59")
        assert result.is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
