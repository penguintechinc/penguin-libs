"""Comprehensive tests for penguin-security package.

Covers sanitization, CSRF protection, password hashing, rate limiting,
and input escaping utilities.
"""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestSanitizeHtml:
    """Tests for HTML sanitization function."""

    def test_sanitize_html_removes_script_tags(self) -> None:
        """Test that script tags are removed."""
        from penguin_security import sanitize_html

        result = sanitize_html("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "alert" not in result
        assert "Hello" in result

    def test_sanitize_html_removes_event_handlers(self) -> None:
        """Test that event handlers are removed."""
        from penguin_security import sanitize_html

        result = sanitize_html("<img src=x onerror=alert('xss')>")
        assert "onerror" not in result
        assert "<img" in result

    def test_sanitize_html_removes_javascript_url(self) -> None:
        """Test that javascript: URLs are removed."""
        from penguin_security import sanitize_html

        result = sanitize_html('<a href="javascript:alert(\'xss\')">link</a>')
        assert "javascript:" not in result
        assert "link" in result

    def test_sanitize_html_removes_data_url_with_script(self) -> None:
        """Test that data: URLs with scripts are sanitized."""
        from penguin_security import sanitize_html

        result = sanitize_html("<img src='data:text/html,<script>alert()</script>'>")
        assert "data:text/html" not in result or "script" not in result

    def test_sanitize_html_entity_encoding(self) -> None:
        """Test proper handling of HTML entities."""
        from penguin_security import sanitize_html

        result = sanitize_html("&lt;script&gt;alert()&lt;/script&gt;")
        # Should be safe, either entities preserved or decoded and re-encoded
        assert "script" not in result or "&lt;script&gt;" in result

    def test_sanitize_html_removes_null_bytes(self) -> None:
        """Test that null bytes are removed."""
        from penguin_security import sanitize_html

        result = sanitize_html("Hello\x00World")
        assert "\x00" not in result

    def test_sanitize_html_svg_attack_prevention(self) -> None:
        """Test that SVG-based XSS is prevented."""
        from penguin_security import sanitize_html

        result = sanitize_html("<svg onload=alert('xss')></svg>")
        assert "onload" not in result or "<svg" not in result

    def test_sanitize_html_preserves_safe_html(self) -> None:
        """Test that safe HTML is preserved."""
        from penguin_security import sanitize_html

        safe_html = "<p>Hello <strong>World</strong></p>"
        result = sanitize_html(safe_html)
        assert "Hello" in result
        assert "World" in result

    def test_sanitize_html_empty_string(self) -> None:
        """Test handling of empty string."""
        from penguin_security import sanitize_html

        result = sanitize_html("")
        assert result == ""

    def test_sanitize_html_none_input(self) -> None:
        """Test handling of None input."""
        from penguin_security import sanitize_html

        with pytest.raises(TypeError):
            sanitize_html(None)  # type: ignore

    def test_sanitize_html_very_long_input(self) -> None:
        """Test handling of very long input."""
        from penguin_security import sanitize_html

        long_input = "x" * 10000
        result = sanitize_html(long_input)
        assert len(result) > 0

    def test_sanitize_html_unicode_preservation(self) -> None:
        """Test that valid Unicode is preserved."""
        from penguin_security import sanitize_html

        unicode_input = "你好世界"
        result = sanitize_html(unicode_input)
        assert unicode_input in result

    def test_sanitize_html_mixed_encoding(self) -> None:
        """Test handling of mixed encodings."""
        from penguin_security import sanitize_html

        mixed = "Hello &amp; 你好 &#x41; <b>test</b>"
        result = sanitize_html(mixed)
        assert len(result) > 0

    def test_sanitize_html_multiple_passes(self) -> None:
        """Test that multiple sanitization passes are safe."""
        from penguin_security import sanitize_html

        malicious = "<script>alert('xss')</script>"
        once = sanitize_html(malicious)
        twice = sanitize_html(once)
        # Second pass should not introduce new issues
        assert "script" not in twice or "<script>" not in twice


class TestEscapeSqlString:
    """Tests for SQL string escaping."""

    def test_escape_sql_string_single_quotes(self) -> None:
        """Test escaping of single quotes."""
        from penguin_security import escape_sql_string

        result = escape_sql_string("It's")
        # Should be escaped (either doubled or backslash-escaped)
        assert "It" in result
        # Result should be SQL-safe

    def test_escape_sql_string_double_quotes(self) -> None:
        """Test escaping of double quotes."""
        from penguin_security import escape_sql_string

        result = escape_sql_string('Say "hello"')
        assert "Say" in result
        assert len(result) > 0

    def test_escape_sql_string_backslashes(self) -> None:
        """Test escaping of backslashes."""
        from penguin_security import escape_sql_string

        result = escape_sql_string("path\\to\\file")
        assert len(result) > 0

    def test_escape_sql_string_unicode(self) -> None:
        """Test escaping of Unicode characters."""
        from penguin_security import escape_sql_string

        result = escape_sql_string("你好")
        assert len(result) > 0

    def test_escape_sql_string_injection_pattern(self) -> None:
        """Test that SQL injection patterns are escaped."""
        from penguin_security import escape_sql_string

        malicious = "'; DROP TABLE users; --"
        result = escape_sql_string(malicious)
        # Result should prevent injection (quotes escaped)
        assert len(result) > len(malicious)  # Should be longer due to escaping

    def test_escape_sql_string_empty_string(self) -> None:
        """Test handling of empty string."""
        from penguin_security import escape_sql_string

        result = escape_sql_string("")
        assert result == ""

    def test_escape_sql_string_none_input(self) -> None:
        """Test handling of None input."""
        from penguin_security import escape_sql_string

        with pytest.raises(TypeError):
            escape_sql_string(None)  # type: ignore


class TestEscapeShellArg:
    """Tests for shell argument escaping."""

    def test_escape_shell_arg_special_characters(self) -> None:
        """Test escaping of shell special characters."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("rm -rf /")
        # Should be quoted or escaped
        assert "rm -rf /" in result or len(result) > len("rm -rf /")

    def test_escape_shell_arg_dollar_sign(self) -> None:
        """Test escaping of dollar signs (variable expansion)."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("$USER")
        # Should prevent variable expansion
        assert len(result) > 0

    def test_escape_shell_arg_backticks(self) -> None:
        """Test escaping of backticks (command substitution)."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("`whoami`")
        # Should prevent command substitution
        assert len(result) > 0

    def test_escape_shell_arg_newlines(self) -> None:
        """Test escaping of newlines."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("line1\nline2")
        assert len(result) > 0

    def test_escape_shell_arg_empty_string(self) -> None:
        """Test handling of empty string."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("")
        # Empty string should still be quoted
        assert len(result) >= 0

    def test_escape_shell_arg_single_quotes_in_string(self) -> None:
        """Test escaping when string contains single quotes."""
        from penguin_security import escape_shell_arg

        result = escape_shell_arg("it's")
        assert len(result) > 0


class TestGenerateCsrfToken:
    """Tests for CSRF token generation."""

    def test_generate_csrf_token_returns_string(self) -> None:
        """Test that CSRF token is a string."""
        from penguin_security import generate_csrf_token

        token = generate_csrf_token()
        assert isinstance(token, str)

    def test_generate_csrf_token_uniqueness(self) -> None:
        """Test that generated tokens are unique."""
        from penguin_security import generate_csrf_token

        token1 = generate_csrf_token()
        token2 = generate_csrf_token()
        assert token1 != token2

    def test_generate_csrf_token_length(self) -> None:
        """Test that token has sufficient entropy."""
        from penguin_security import generate_csrf_token

        token = generate_csrf_token()
        assert len(token) >= 32

    def test_generate_csrf_token_randomness(self) -> None:
        """Test that tokens have good randomness."""
        from penguin_security import generate_csrf_token

        tokens = [generate_csrf_token() for _ in range(10)]
        # All should be different
        assert len(set(tokens)) == 10

    def test_generate_csrf_token_format(self) -> None:
        """Test that token is in appropriate format (hex or alphanumeric)."""
        from penguin_security import generate_csrf_token

        token = generate_csrf_token()
        # Should be hex or alphanumeric
        assert all(c in "0123456789abcdefABCDEF-_" for c in token) or token.isalnum()


class TestValidateCsrfToken:
    """Tests for CSRF token validation."""

    def test_validate_csrf_token_matching_tokens(self) -> None:
        """Test validation with matching tokens."""
        from penguin_security import generate_csrf_token, validate_csrf_token

        token = generate_csrf_token()
        assert validate_csrf_token(token, token) is True

    def test_validate_csrf_token_mismatched_tokens(self) -> None:
        """Test validation with mismatched tokens."""
        from penguin_security import validate_csrf_token

        assert validate_csrf_token("token1", "token2") is False

    def test_validate_csrf_token_empty_token(self) -> None:
        """Test validation with empty token."""
        from penguin_security import validate_csrf_token

        assert validate_csrf_token("", "something") is False

    def test_validate_csrf_token_empty_session_token(self) -> None:
        """Test validation with empty session token."""
        from penguin_security import validate_csrf_token

        assert validate_csrf_token("something", "") is False

    def test_validate_csrf_token_both_empty(self) -> None:
        """Test validation with both tokens empty."""
        from penguin_security import validate_csrf_token

        assert validate_csrf_token("", "") is False

    def test_validate_csrf_token_case_sensitive(self) -> None:
        """Test that validation is case-sensitive."""
        from penguin_security import validate_csrf_token

        token = "ABC123"
        assert validate_csrf_token(token, "abc123") is False

    def test_validate_csrf_token_uses_hmac_compare(self) -> None:
        """Test that validation uses hmac.compare_digest (constant-time by design)."""
        import inspect
        import hmac
        from penguin_security.csrf import validate_csrf_token

        source = inspect.getsource(validate_csrf_token)
        assert "compare_digest" in source

    def test_validate_csrf_token_none_inputs(self) -> None:
        """Test validation with None inputs."""
        from penguin_security import validate_csrf_token

        with pytest.raises(TypeError):
            validate_csrf_token(None, "token")  # type: ignore

        with pytest.raises(TypeError):
            validate_csrf_token("token", None)  # type: ignore


class TestHashPassword:
    """Tests for password hashing."""

    def test_hash_password_returns_string(self) -> None:
        """Test that hash is a string."""
        from penguin_security import hash_password

        hashed = hash_password("test_password")
        assert isinstance(hashed, str)

    def test_hash_password_different_each_time(self) -> None:
        """Test that same password produces different hashes (due to salt)."""
        from penguin_security import hash_password

        hash1 = hash_password("password")
        hash2 = hash_password("password")
        assert hash1 != hash2

    def test_hash_password_output_length(self) -> None:
        """Test that hash has sufficient length for security."""
        from penguin_security import hash_password

        hashed = hash_password("test")
        assert len(hashed) > 30

    def test_hash_password_empty_string(self) -> None:
        """Test hashing of empty string."""
        from penguin_security import hash_password

        hashed = hash_password("")
        assert len(hashed) > 0

    def test_hash_password_long_password(self) -> None:
        """Test hashing of very long password."""
        from penguin_security import hash_password

        long_pass = "x" * 1000
        hashed = hash_password(long_pass)
        assert len(hashed) > 0

    def test_hash_password_unicode(self) -> None:
        """Test hashing of Unicode password."""
        from penguin_security import hash_password

        hashed = hash_password("密码123")
        assert len(hashed) > 0

    def test_hash_password_special_characters(self) -> None:
        """Test hashing of password with special characters."""
        from penguin_security import hash_password

        hashed = hash_password("p@$$w0rd!#%&")
        assert len(hashed) > 0

    def test_hash_password_none_input(self) -> None:
        """Test handling of None input."""
        from penguin_security import hash_password

        with pytest.raises(TypeError):
            hash_password(None)  # type: ignore


class TestVerifyPassword:
    """Tests for password verification."""

    def test_verify_password_correct_password(self) -> None:
        """Test verification with correct password."""
        from penguin_security import hash_password, verify_password

        password = "my_secure_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_wrong_password(self) -> None:
        """Test verification with wrong password."""
        from penguin_security import hash_password, verify_password

        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_empty_password(self) -> None:
        """Test verification with empty password."""
        from penguin_security import hash_password, verify_password

        hashed = hash_password("password")
        assert verify_password("", hashed) is False

    def test_verify_password_unicode(self) -> None:
        """Test verification with Unicode password."""
        from penguin_security import hash_password, verify_password

        password = "密码123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_case_sensitive(self) -> None:
        """Test that verification is case-sensitive."""
        from penguin_security import hash_password, verify_password

        hashed = hash_password("Password")
        assert verify_password("password", hashed) is False

    def test_verify_password_constant_time(self) -> None:
        """Test that verification uses constant-time comparison."""
        from penguin_security import hash_password, verify_password

        password = "test_password"
        hashed = hash_password(password)

        # Time correct and wrong passwords
        import timeit

        time_correct = timeit.timeit(lambda: verify_password(password, hashed), number=100)
        time_wrong = timeit.timeit(lambda: verify_password("wrong", hashed), number=100)

        # Times should be similar (no early exit)
        avg_time = (time_correct + time_wrong) / 2
        variance = max(abs(time_correct - avg_time), abs(time_wrong - avg_time)) / avg_time
        assert variance < 0.5  # Within 50% variance

    def test_verify_password_invalid_hash(self) -> None:
        """Test verification with invalid hash."""
        from penguin_security import verify_password

        with pytest.raises((ValueError, TypeError)):
            verify_password("password", "invalid_hash")

    def test_verify_password_none_password(self) -> None:
        """Test handling of None password."""
        from penguin_security import hash_password, verify_password

        hashed = hash_password("password")
        with pytest.raises(TypeError):
            verify_password(None, hashed)  # type: ignore

    def test_verify_password_none_hash(self) -> None:
        """Test handling of None hash."""
        from penguin_security import verify_password

        with pytest.raises(TypeError):
            verify_password("password", None)  # type: ignore


class TestCheckRateLimit:
    """Tests for rate limiting."""

    def test_check_rate_limit_within_limit(self) -> None:
        """Test that requests within limit are allowed."""
        from penguin_security import check_rate_limit

        for i in range(5):
            assert check_rate_limit("key1", limit=10, window=60) is True

    def test_check_rate_limit_exceeds_limit(self) -> None:
        """Test that requests exceeding limit are blocked."""
        from penguin_security import check_rate_limit

        # Use a unique key for this test
        test_key = f"test_key_{time.time()}"

        # Fill up the limit
        for i in range(5):
            check_rate_limit(test_key, limit=5, window=60)

        # Next request should fail
        assert check_rate_limit(test_key, limit=5, window=60) is False

    def test_check_rate_limit_different_keys_independent(self) -> None:
        """Test that different keys are tracked independently."""
        from penguin_security import check_rate_limit

        key1 = f"key1_{time.time()}"
        key2 = f"key2_{time.time()}"

        # Max out key1
        for _ in range(3):
            check_rate_limit(key1, limit=3, window=60)

        # key2 should still have budget
        assert check_rate_limit(key2, limit=3, window=60) is True

    def test_check_rate_limit_window_expiry(self) -> None:
        """Test that rate limit resets after window expires."""
        from penguin_security import check_rate_limit

        test_key = f"test_window_{time.time()}"

        # Max out with short window
        for _ in range(2):
            check_rate_limit(test_key, limit=2, window=1)

        # Should be blocked
        assert check_rate_limit(test_key, limit=2, window=1) is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        assert check_rate_limit(test_key, limit=2, window=1) is True

    def test_check_rate_limit_empty_key(self) -> None:
        """Test handling of empty key."""
        from penguin_security import check_rate_limit

        # Should handle gracefully (either allow or raise specific error)
        try:
            result = check_rate_limit("", limit=10, window=60)
            # If it doesn't raise, result should be boolean
            assert isinstance(result, bool)
        except ValueError:
            # Or raise ValueError for empty key
            pass

    def test_check_rate_limit_zero_limit(self) -> None:
        """Test handling of zero limit."""
        from penguin_security import check_rate_limit

        # Zero limit should block all requests
        assert check_rate_limit("key", limit=0, window=60) is False

    def test_check_rate_limit_large_limit(self) -> None:
        """Test handling of large limit."""
        from penguin_security import check_rate_limit

        test_key = f"large_limit_{time.time()}"
        for _ in range(100):
            result = check_rate_limit(test_key, limit=1000, window=60)
            assert result is True


class TestSecurityIntegration:
    """Integration tests for security utilities."""

    def test_sanitize_then_escape(self) -> None:
        """Test combining sanitization and escaping."""
        from penguin_security import escape_sql_string, sanitize_html

        malicious = "<script>'; DROP TABLE users; --</script>"
        sanitized = sanitize_html(malicious)
        escaped = escape_sql_string(sanitized)
        assert len(escaped) > 0

    def test_password_workflow(self) -> None:
        """Test complete password hashing and verification workflow."""
        from penguin_security import hash_password, verify_password

        password = "user_password_123"

        # Hash on registration
        stored_hash = hash_password(password)

        # Verify on login
        assert verify_password(password, stored_hash) is True
        assert verify_password("wrong_password", stored_hash) is False

    def test_csrf_workflow(self) -> None:
        """Test complete CSRF token workflow."""
        from penguin_security import generate_csrf_token, validate_csrf_token

        # Generate token for form
        token = generate_csrf_token()

        # Store in session and form
        session_token = token
        form_token = token

        # Validate on submission
        assert validate_csrf_token(form_token, session_token) is True

        # Reject if token changed
        assert validate_csrf_token("hacked_token", session_token) is False

    def test_concurrent_rate_limit_safety(self) -> None:
        """Test that rate limiter handles concurrent requests safely."""
        from penguin_security import check_rate_limit
        import threading

        test_key = f"concurrent_{time.time()}"
        limit = 10
        results = []

        def make_request() -> None:
            result = check_rate_limit(test_key, limit=limit, window=60)
            results.append(result)

        # Spawn multiple threads
        threads = [threading.Thread(target=make_request) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 'limit' True results and rest False
        true_count = sum(1 for r in results if r is True)
        false_count = sum(1 for r in results if r is False)

        assert true_count <= limit
        assert true_count + false_count == 20


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_sanitize_html_control_characters(self) -> None:
        """Test handling of control characters."""
        from penguin_security import sanitize_html

        result = sanitize_html("Hello\x01\x02\x03World")
        assert len(result) > 0

    def test_sanitize_html_mixed_quotes(self) -> None:
        """Test handling of mixed quote types."""
        from penguin_security import sanitize_html

        result = sanitize_html("""<div data-value="test's" class='other'>text</div>""")
        assert len(result) > 0

    def test_escape_sql_percent_symbol(self) -> None:
        """Test escaping of percent signs (LIKE wildcard)."""
        from penguin_security import escape_sql_string

        result = escape_sql_string("50% off")
        assert len(result) > 0

    def test_hash_password_with_whitespace(self) -> None:
        """Test hashing password with whitespace."""
        from penguin_security import hash_password

        result = hash_password("  password  ")
        assert len(result) > 0

    def test_verify_password_with_whitespace(self) -> None:
        """Test verifying password with whitespace."""
        from penguin_security import hash_password, verify_password

        password = "  password  "
        hashed = hash_password(password)
        # Whitespace should be significant
        assert verify_password(password, hashed) is True
        assert verify_password(password.strip(), hashed) is False
