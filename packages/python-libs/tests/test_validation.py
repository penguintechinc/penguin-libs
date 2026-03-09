"""Tests for penguin_libs.validation module."""

import re
from datetime import date, datetime, time

import pytest

from penguin_libs.validation import (
    IsAlphanumeric,
    IsDate,
    IsDateInRange,
    IsDateTime,
    IsEmail,
    IsFloat,
    IsFloatInRange,
    IsHostname,
    IsIPAddress,
    IsIn,
    IsInt,
    IsIntInRange,
    IsLength,
    IsMatch,
    IsNegative,
    IsNotEmpty,
    IsPositive,
    IsSlug,
    IsStrongPassword,
    IsTime,
    IsTrimmed,
    IsURL,
    PasswordOptions,
    ValidationError,
    ValidationResult,
    Validator,
    chain,
)


# ──────────────────────── base.py ────────────────────────


class TestValidationError:
    def test_message_only(self):
        err = ValidationError("bad value")
        assert str(err) == "bad value"
        assert err.message == "bad value"
        assert err.field is None

    def test_with_field(self):
        err = ValidationError("required", field="email")
        assert str(err) == "email: required"
        assert err.field == "email"


class TestValidationResult:
    def test_success(self):
        r = ValidationResult.success("ok")
        assert r.is_valid is True
        assert r.value == "ok"
        assert r.error is None

    def test_failure(self):
        r = ValidationResult.failure("nope")
        assert r.is_valid is False
        assert r.value is None
        assert r.error == "nope"

    def test_unwrap_success(self):
        assert ValidationResult.success(42).unwrap() == 42

    def test_unwrap_failure_raises(self):
        with pytest.raises(ValidationError, match="bad"):
            ValidationResult.failure("bad").unwrap()

    def test_unwrap_failure_default_message(self):
        r = ValidationResult(is_valid=False, value=None, error=None)
        with pytest.raises(ValidationError, match="Validation failed"):
            r.unwrap()

    def test_unwrap_or_success(self):
        assert ValidationResult.success(10).unwrap_or(0) == 10

    def test_unwrap_or_failure(self):
        assert ValidationResult.failure("x").unwrap_or(99) == 99

    def test_unwrap_or_none_value(self):
        r = ValidationResult(is_valid=True, value=None, error=None)
        assert r.unwrap_or("default") == "default"


class TestChainedValidator:
    def test_chain_function(self):
        v = chain(IsNotEmpty(), IsLength(3, 50))
        r = v("hello")
        assert r.is_valid
        assert r.value == "hello"

    def test_chain_fails_early(self):
        v = chain(IsNotEmpty(), IsLength(10, 50))
        r = v("hi")
        assert not r.is_valid

    def test_and_then(self):
        v = IsNotEmpty().and_then(IsLength(1, 10))
        r = v("ok")
        assert r.is_valid

    def test_chained_and_then(self):
        v = chain(IsNotEmpty(), IsLength(1, 10)).and_then(IsMatch(r"^[a-z]+$"))
        r = v("hello")
        assert r.is_valid
        r2 = v("HELLO")
        assert not r2.is_valid

    def test_chain_failure_message(self):
        v = chain(IsNotEmpty(), IsLength(10, 20))
        r = v("ab")
        assert not r.is_valid
        assert r.error is not None


# ──────────────────────── string.py ────────────────────────


class TestIsNotEmpty:
    def test_valid(self):
        assert IsNotEmpty()("hello").is_valid

    def test_strips_whitespace(self):
        r = IsNotEmpty()("  hello  ")
        assert r.value == "hello"

    def test_empty_string(self):
        assert not IsNotEmpty()("").is_valid

    def test_whitespace_only(self):
        assert not IsNotEmpty()("   ").is_valid

    def test_non_string(self):
        assert not IsNotEmpty()(123).is_valid

    def test_custom_message(self):
        r = IsNotEmpty(error_message="required!")("")
        assert r.error == "required!"


class TestIsLength:
    def test_valid_range(self):
        assert IsLength(3, 10)("hello").is_valid

    def test_too_short(self):
        r = IsLength(5)("hi")
        assert not r.is_valid
        assert "at least 5" in r.error

    def test_too_long(self):
        r = IsLength(0, 3)("hello")
        assert not r.is_valid
        assert "at most 3" in r.error

    def test_no_max(self):
        assert IsLength(1)("x" * 1000).is_valid

    def test_non_string(self):
        assert not IsLength()(42).is_valid

    def test_custom_message(self):
        r = IsLength(5, error_message="too short!")("hi")
        assert r.error == "too short!"

    def test_custom_message_max(self):
        r = IsLength(0, 2, error_message="too long!")("abc")
        assert r.error == "too long!"


class TestIsMatch:
    def test_valid_pattern(self):
        assert IsMatch(r"^\d{3}$")("123").is_valid

    def test_invalid_pattern(self):
        assert not IsMatch(r"^\d{3}$")("abc").is_valid

    def test_compiled_pattern(self):
        pat = re.compile(r"^[A-Z]+$")
        assert IsMatch(pat)("ABC").is_valid

    def test_flags(self):
        assert IsMatch(r"^hello$", re.IGNORECASE)("HELLO").is_valid

    def test_non_string(self):
        assert not IsMatch(r".*")(42).is_valid

    def test_custom_message(self):
        r = IsMatch(r"^\d+$", error_message="numbers only")("abc")
        assert r.error == "numbers only"


class TestIsAlphanumeric:
    def test_valid(self):
        assert IsAlphanumeric()("Hello123").is_valid

    def test_special_chars_rejected(self):
        assert not IsAlphanumeric()("Hello!").is_valid

    def test_underscore_allowed(self):
        assert IsAlphanumeric(allow_underscore=True)("hello_world").is_valid

    def test_dash_allowed(self):
        assert IsAlphanumeric(allow_dash=True)("hello-world").is_valid

    def test_empty_string(self):
        assert not IsAlphanumeric()("").is_valid

    def test_non_string(self):
        assert not IsAlphanumeric()(42).is_valid

    def test_custom_message(self):
        r = IsAlphanumeric(error_message="alnum only")("bad!")
        assert r.error == "alnum only"


class TestIsSlug:
    def test_valid(self):
        assert IsSlug()("my-blog-post").is_valid

    def test_single_word(self):
        assert IsSlug()("hello").is_valid

    def test_with_numbers(self):
        assert IsSlug()("post-123").is_valid

    def test_uppercase_rejected(self):
        assert not IsSlug()("My-Post").is_valid

    def test_consecutive_hyphens(self):
        assert not IsSlug()("my--post").is_valid

    def test_leading_hyphen(self):
        assert not IsSlug()("-my-post").is_valid

    def test_empty(self):
        assert not IsSlug()("").is_valid

    def test_non_string(self):
        assert not IsSlug()(42).is_valid

    def test_custom_message(self):
        r = IsSlug(error_message="bad slug")("BAD!")
        assert r.error == "bad slug"


class TestIsIn:
    def test_valid(self):
        assert IsIn(["a", "b", "c"])("a").is_valid

    def test_invalid(self):
        assert not IsIn(["a", "b"])("z").is_valid

    def test_case_sensitive(self):
        assert not IsIn(["admin"])("Admin").is_valid

    def test_case_insensitive(self):
        assert IsIn(["admin"], case_sensitive=False)("ADMIN").is_valid

    def test_non_string(self):
        assert not IsIn(["a"])(42).is_valid

    def test_custom_message(self):
        r = IsIn(["x"], error_message="not allowed")("y")
        assert r.error == "not allowed"

    def test_default_message_lists_options(self):
        r = IsIn(["a", "b"])("z")
        assert "a, b" in r.error


class TestIsTrimmed:
    def test_trims(self):
        r = IsTrimmed()("  hello  ")
        assert r.value == "hello"

    def test_empty_disallowed(self):
        assert not IsTrimmed()("   ").is_valid

    def test_empty_allowed(self):
        r = IsTrimmed(allow_empty=True)("   ")
        assert r.is_valid
        assert r.value == ""

    def test_non_string(self):
        assert not IsTrimmed()(42).is_valid


# ──────────────────────── numeric.py ────────────────────────


class TestIsInt:
    def test_int_value(self):
        r = IsInt()(42)
        assert r.is_valid and r.value == 42

    def test_string_int(self):
        r = IsInt()("42")
        assert r.is_valid and r.value == 42

    def test_float_integer(self):
        r = IsInt()(5.0)
        assert r.is_valid and r.value == 5

    def test_float_non_integer(self):
        assert not IsInt()(3.14).is_valid

    def test_bool_rejected(self):
        assert not IsInt()(True).is_valid

    def test_string_float(self):
        assert not IsInt()("3.14").is_valid

    def test_string_scientific(self):
        assert not IsInt()("1e5").is_valid

    def test_non_numeric(self):
        assert not IsInt()("abc").is_valid

    def test_custom_message(self):
        r = IsInt(error_message="int please")("abc")
        assert r.error == "int please"

    def test_unsupported_type(self):
        assert not IsInt()([1, 2]).is_valid


class TestIsFloat:
    def test_float_value(self):
        r = IsFloat()(3.14)
        assert r.is_valid and r.value == 3.14

    def test_int_to_float(self):
        r = IsFloat()(42)
        assert r.is_valid and r.value == 42.0

    def test_string_float(self):
        r = IsFloat()("3.14")
        assert r.is_valid and r.value == 3.14

    def test_bool_rejected(self):
        assert not IsFloat()(False).is_valid

    def test_non_numeric(self):
        assert not IsFloat()("abc").is_valid

    def test_unsupported_type(self):
        assert not IsFloat()([]).is_valid


class TestIsIntInRange:
    def test_in_range(self):
        r = IsIntInRange(1, 100)(50)
        assert r.is_valid and r.value == 50

    def test_below_min(self):
        r = IsIntInRange(10)(5)
        assert not r.is_valid
        assert "at least 10" in r.error

    def test_above_max(self):
        r = IsIntInRange(None, 10)(15)
        assert not r.is_valid
        assert "at most 10" in r.error

    def test_not_int(self):
        assert not IsIntInRange(1, 10)("abc").is_valid

    def test_custom_message(self):
        r = IsIntInRange(10, error_message="out of range")(5)
        assert r.error == "out of range"

    def test_custom_message_max(self):
        r = IsIntInRange(None, 10, error_message="too big")(15)
        assert r.error == "too big"

    def test_no_bounds(self):
        assert IsIntInRange()(999).is_valid


class TestIsFloatInRange:
    def test_in_range(self):
        r = IsFloatInRange(0.0, 1.0)(0.5)
        assert r.is_valid and r.value == 0.5

    def test_below_min(self):
        r = IsFloatInRange(0.0)(-0.1)
        assert not r.is_valid

    def test_above_max(self):
        r = IsFloatInRange(None, 1.0)(1.5)
        assert not r.is_valid

    def test_not_number(self):
        assert not IsFloatInRange()("abc").is_valid

    def test_custom_message_min(self):
        r = IsFloatInRange(0.0, error_message="positive!")(-1.0)
        assert r.error == "positive!"

    def test_custom_message_max(self):
        r = IsFloatInRange(None, 1.0, error_message="too big!")(2.0)
        assert r.error == "too big!"


class TestIsPositive:
    def test_positive(self):
        assert IsPositive()(5).is_valid

    def test_zero_rejected(self):
        assert not IsPositive()(0).is_valid

    def test_zero_allowed(self):
        assert IsPositive(allow_zero=True)(0).is_valid

    def test_negative_rejected(self):
        assert not IsPositive()(-1).is_valid

    def test_negative_with_allow_zero(self):
        assert not IsPositive(allow_zero=True)(-1).is_valid

    def test_non_number(self):
        assert not IsPositive()("abc").is_valid

    def test_custom_message(self):
        r = IsPositive(error_message="must be positive")(-1)
        assert r.error == "must be positive"

    def test_custom_message_allow_zero(self):
        r = IsPositive(allow_zero=True, error_message="non-neg")(-1)
        assert r.error == "non-neg"


class TestIsNegative:
    def test_negative(self):
        assert IsNegative()(-5).is_valid

    def test_zero_rejected(self):
        assert not IsNegative()(0).is_valid

    def test_zero_allowed(self):
        assert IsNegative(allow_zero=True)(0).is_valid

    def test_positive_rejected(self):
        assert not IsNegative()(5).is_valid

    def test_positive_with_allow_zero(self):
        assert not IsNegative(allow_zero=True)(5).is_valid

    def test_non_number(self):
        assert not IsNegative()("abc").is_valid

    def test_custom_message(self):
        r = IsNegative(error_message="must be negative")(1)
        assert r.error == "must be negative"

    def test_custom_message_allow_zero(self):
        r = IsNegative(allow_zero=True, error_message="non-pos")(1)
        assert r.error == "non-pos"


# ──────────────────────── network.py ────────────────────────


class TestIsEmail:
    def test_valid(self):
        r = IsEmail()("user@example.com")
        assert r.is_valid and r.value == "user@example.com"

    def test_normalizes(self):
        r = IsEmail()("User@Example.COM")
        assert r.value == "user@example.com"

    def test_no_normalize(self):
        r = IsEmail(normalize=False)("User@Example.COM")
        assert r.value == "User@Example.COM"

    def test_invalid(self):
        assert not IsEmail()("not-an-email").is_valid

    def test_empty(self):
        assert not IsEmail()("").is_valid

    def test_too_long(self):
        assert not IsEmail()("a" * 255 + "@example.com").is_valid

    def test_local_part_too_long(self):
        assert not IsEmail()("a" * 65 + "@example.com").is_valid

    def test_non_string(self):
        assert not IsEmail()(42).is_valid

    def test_strips_whitespace(self):
        r = IsEmail()("  user@example.com  ")
        assert r.is_valid

    def test_custom_message(self):
        r = IsEmail(error_message="bad email")("x")
        assert r.error == "bad email"


class TestIsURL:
    def test_valid_https(self):
        assert IsURL()("https://example.com").is_valid

    def test_valid_http(self):
        assert IsURL()("http://example.com").is_valid

    def test_no_scheme(self):
        assert not IsURL()("example.com").is_valid

    def test_invalid_scheme(self):
        r = IsURL()("ftp://example.com")
        assert not r.is_valid
        assert "scheme" in r.error.lower()

    def test_allowed_schemes(self):
        assert IsURL(allowed_schemes=["ftp"])("ftp://files.example.com").is_valid

    def test_no_netloc(self):
        assert not IsURL()("http://").is_valid

    def test_require_tld_no_dot(self):
        assert not IsURL()("http://myserver").is_valid

    def test_localhost_allowed(self):
        assert IsURL()("http://localhost").is_valid

    def test_no_tld_required(self):
        assert IsURL(require_tld=False)("http://myserver").is_valid

    def test_empty(self):
        assert not IsURL()("").is_valid

    def test_non_string(self):
        assert not IsURL()(42).is_valid

    def test_with_port_and_userinfo(self):
        assert IsURL()("http://user@example.com:8080/path").is_valid


class TestIsIPAddress:
    def test_ipv4(self):
        assert IsIPAddress()("192.168.1.1").is_valid

    def test_ipv6(self):
        assert IsIPAddress()("::1").is_valid

    def test_invalid(self):
        assert not IsIPAddress()("not-an-ip").is_valid

    def test_v4_only(self):
        assert IsIPAddress(version=4)("192.168.1.1").is_valid
        assert not IsIPAddress(version=4)("::1").is_valid

    def test_v6_only(self):
        assert IsIPAddress(version=6)("::1").is_valid
        assert not IsIPAddress(version=6)("192.168.1.1").is_valid

    def test_invalid_version(self):
        with pytest.raises(ValueError, match="version must be 4, 6"):
            IsIPAddress(version=5)

    def test_empty(self):
        assert not IsIPAddress()("").is_valid

    def test_non_string(self):
        assert not IsIPAddress()(42).is_valid

    def test_error_messages(self):
        r4 = IsIPAddress(version=4)("bad")
        assert "IPv4" in r4.error
        r6 = IsIPAddress(version=6)("bad")
        assert "IPv6" in r6.error
        r = IsIPAddress()("bad")
        assert "IP address" in r.error

    def test_custom_message(self):
        r = IsIPAddress(error_message="bad ip")("bad")
        assert r.error == "bad ip"


class TestIsHostname:
    def test_valid_fqdn(self):
        r = IsHostname()("example.com")
        assert r.is_valid and r.value == "example.com"

    def test_single_label(self):
        assert IsHostname()("myserver").is_valid

    def test_normalizes_lowercase(self):
        r = IsHostname()("Example.COM")
        assert r.value == "example.com"

    def test_invalid_chars(self):
        assert not IsHostname()("invalid..com").is_valid

    def test_leading_hyphen(self):
        assert not IsHostname()("-invalid.com").is_valid

    def test_too_long(self):
        assert not IsHostname()("a" * 254).is_valid

    def test_empty(self):
        assert not IsHostname()("").is_valid

    def test_non_string(self):
        assert not IsHostname()(42).is_valid

    def test_allow_ip(self):
        assert IsHostname(allow_ip=True)("192.168.1.1").is_valid

    def test_require_tld(self):
        assert not IsHostname(require_tld=True)("myserver").is_valid
        assert IsHostname(require_tld=True)("example.com").is_valid

    def test_custom_message(self):
        r = IsHostname(error_message="bad host")("--bad")
        assert r.error == "bad host"


# ──────────────────────── datetime.py ────────────────────────


class TestIsDate:
    def test_valid_string(self):
        r = IsDate()("2024-01-15")
        assert r.is_valid and r.value == date(2024, 1, 15)

    def test_date_object(self):
        d = date(2024, 6, 1)
        r = IsDate()(d)
        assert r.is_valid and r.value == d

    def test_datetime_object(self):
        dt = datetime(2024, 6, 1, 12, 0)
        r = IsDate()(dt)
        assert r.is_valid and r.value == date(2024, 6, 1)

    def test_custom_format(self):
        r = IsDate(format="%d/%m/%Y")("15/01/2024")
        assert r.is_valid

    def test_invalid_format(self):
        r = IsDate()("15/01/2024")
        assert not r.is_valid
        assert "Expected" in r.error

    def test_empty(self):
        assert not IsDate()("").is_valid

    def test_non_date_type(self):
        assert not IsDate()(42).is_valid

    def test_custom_message(self):
        r = IsDate(error_message="bad date")("nope")
        assert r.error == "bad date"


class TestIsDateTime:
    def test_valid_string(self):
        r = IsDateTime()("2024-01-15T14:30:00")
        assert r.is_valid
        assert r.value == datetime(2024, 1, 15, 14, 30, 0)

    def test_datetime_object(self):
        dt = datetime(2024, 1, 1, 0, 0)
        assert IsDateTime()(dt).is_valid

    def test_custom_format(self):
        r = IsDateTime(format="%Y-%m-%d %H:%M")("2024-01-15 14:30")
        assert r.is_valid

    def test_invalid_format(self):
        assert not IsDateTime()("2024-01-15").is_valid

    def test_empty(self):
        assert not IsDateTime()("").is_valid

    def test_non_datetime_type(self):
        assert not IsDateTime()(42).is_valid

    def test_custom_message(self):
        r = IsDateTime(error_message="bad dt")("nope")
        assert r.error == "bad dt"


class TestIsTime:
    def test_valid_string(self):
        r = IsTime()("14:30:00")
        assert r.is_valid and r.value == time(14, 30, 0)

    def test_time_object(self):
        t = time(12, 0)
        assert IsTime()(t).is_valid

    def test_datetime_object(self):
        dt = datetime(2024, 1, 1, 14, 30)
        r = IsTime()(dt)
        assert r.is_valid and r.value == time(14, 30)

    def test_custom_format(self):
        r = IsTime(format="%H:%M")("14:30")
        assert r.is_valid

    def test_invalid_format(self):
        assert not IsTime()("14:30").is_valid  # missing seconds

    def test_empty(self):
        assert not IsTime()("").is_valid

    def test_non_time_type(self):
        assert not IsTime()(42).is_valid

    def test_custom_message(self):
        r = IsTime(error_message="bad time")("nope")
        assert r.error == "bad time"


class TestIsDateInRange:
    def test_in_range(self):
        v = IsDateInRange(min_date=date(2024, 1, 1), max_date=date(2024, 12, 31))
        assert v("2024-06-15").is_valid

    def test_before_min(self):
        v = IsDateInRange(min_date=date(2024, 1, 1))
        r = v("2023-12-31")
        assert not r.is_valid
        assert "on or after" in r.error

    def test_after_max(self):
        v = IsDateInRange(max_date=date(2024, 12, 31))
        r = v("2025-01-01")
        assert not r.is_valid
        assert "on or before" in r.error

    def test_invalid_date(self):
        v = IsDateInRange()
        assert not v("not-a-date").is_valid

    def test_custom_message_min(self):
        v = IsDateInRange(min_date=date(2024, 1, 1), error_message="too early")
        r = v("2023-01-01")
        assert r.error == "too early"

    def test_custom_message_max(self):
        v = IsDateInRange(max_date=date(2024, 1, 1), error_message="too late")
        r = v("2025-01-01")
        assert r.error == "too late"

    def test_no_bounds(self):
        assert IsDateInRange()("2024-06-15").is_valid


# ──────────────────────── password.py ────────────────────────


class TestPasswordOptions:
    def test_defaults(self):
        opts = PasswordOptions()
        assert opts.min_length == 8
        assert opts.require_uppercase is True

    def test_weak(self):
        opts = PasswordOptions.weak()
        assert opts.min_length == 6
        assert opts.require_special is False

    def test_moderate(self):
        opts = PasswordOptions.moderate()
        assert opts.min_length == 8
        assert opts.require_special is False
        assert opts.require_uppercase is True

    def test_strong(self):
        opts = PasswordOptions.strong()
        assert opts.min_length == 12
        assert opts.require_special is True

    def test_enterprise(self):
        opts = PasswordOptions.enterprise()
        assert opts.min_length == 16
        assert opts.max_length == 256


class TestIsStrongPassword:
    def test_valid_default(self):
        assert IsStrongPassword()("MyP@ssw0rd!").is_valid

    def test_too_short(self):
        r = IsStrongPassword()("A@1b")
        assert not r.is_valid
        assert "at least" in r.error

    def test_too_long(self):
        r = IsStrongPassword(max_length=10)("A@1b" * 10)
        assert not r.is_valid

    def test_no_uppercase(self):
        r = IsStrongPassword()("myp@ssw0rd!")
        assert not r.is_valid
        assert "uppercase" in r.error

    def test_no_lowercase(self):
        r = IsStrongPassword()("MYP@SSW0RD!")
        assert not r.is_valid
        assert "lowercase" in r.error

    def test_no_digit(self):
        r = IsStrongPassword()("MyP@ssword!")
        assert not r.is_valid
        assert "digit" in r.error

    def test_no_special(self):
        r = IsStrongPassword()("MyPassw0rd1")
        assert not r.is_valid
        assert "special" in r.error

    def test_spaces_disallowed(self):
        r = IsStrongPassword()("My P@ss w0rd!")
        assert not r.is_valid
        assert "spaces" in r.error

    def test_non_string(self):
        assert not IsStrongPassword()(12345).is_valid

    def test_with_options(self):
        v = IsStrongPassword(options=PasswordOptions.weak())
        assert v("simple").is_valid

    def test_kwargs_override(self):
        v = IsStrongPassword(require_special=False, require_uppercase=False)
        assert v("password1").is_valid

    def test_custom_message(self):
        r = IsStrongPassword(error_message="weak!")("a")
        assert r.error == "weak!"

    def test_strength_score(self):
        v = IsStrongPassword()
        score_weak = v.get_strength_score("abc")
        score_strong = v.get_strength_score("MyStr0ng!P@ssw0rd")
        assert score_strong > score_weak
        assert 0 <= score_weak <= 100
        assert 0 <= score_strong <= 100

    def test_strength_score_empty(self):
        v = IsStrongPassword()
        # Empty string: 0 length points, 0 variety, 0 unique ratio,
        # but +10 for no common patterns = 10
        assert v.get_strength_score("") == 10

    def test_strength_score_common_patterns(self):
        v = IsStrongPassword()
        score_common = v.get_strength_score("123password")
        score_unique = v.get_strength_score("Xy!z9Kw#2mQ")
        # Unique password should score higher than common pattern
        assert score_unique > score_common

    def test_strength_score_repeated_chars(self):
        v = IsStrongPassword()
        score = v.get_strength_score("aaaaaa")
        assert score < 50  # Repeated chars should score low


# ──────────────────────── __init__.py ────────────────────────


class TestValidationModuleExports:
    def test_all_exports_importable(self):
        from penguin_libs.validation import __all__

        assert "IsEmail" in __all__
        assert "chain" in __all__
        assert "ValidationResult" in __all__
        assert "IsStrongPassword" in __all__
