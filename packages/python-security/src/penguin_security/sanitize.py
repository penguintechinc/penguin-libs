"""HTML sanitization and XSS prevention utilities."""

import warnings

import nh3


def sanitize_html(text: str) -> str:
    """Sanitize HTML to prevent XSS attacks.

    Uses nh3 (a Rust/ammonia binding) to allowlist-sanitize HTML: only a
    fixed, safe set of tags and attributes survives -- everything else,
    including script tags, event handlers, javascript:/data: URLs, and
    disallowed elements (svg, iframe, object, embed), is stripped.

    This replaces a prior blocklist regex implementation. Blocklist regex
    sanitizers are well-known to be bypassable via malformed/nested tags,
    unusual casing or whitespace, and encoding tricks -- string matching
    can never enumerate every way to spell a dangerous construct. An
    allowlist parser is the only sound defense.

    Args:
        text: HTML string to sanitize

    Returns:
        str: Sanitized HTML string with only allowlisted tags/attributes

    Raises:
        TypeError: If text is not a string
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")

    return nh3.clean(text)


def escape_sql_string(text: str) -> str:
    """Escape SQL string to prevent SQL injection.

    Deprecated: hand-rolled quote-doubling is NOT a substitute for
    parameterized queries and must never be used to build SQL directly.
    Use parameterized queries via penguin-dal (or your driver's native
    parameter binding) instead -- this function is kept only so existing
    importers don't break, and emits a DeprecationWarning on every call.

    Args:
        text: String to escape

    Returns:
        str: Escaped SQL string

    Raises:
        TypeError: If text is not a string
    """
    warnings.warn(
        "escape_sql_string is deprecated and is NOT a substitute for "
        "parameterized queries. Use parameterized queries via penguin-dal "
        "(or your driver's native parameter binding) instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")

    if not text:
        return text

    # Replace single quotes with doubled single quotes (SQL standard)
    escaped = text.replace("'", "''")

    # Also escape backslashes for databases that use backslash escaping
    escaped = escaped.replace("\\", "\\\\")

    return escaped


def escape_shell_arg(text: str) -> str:
    """Escape shell argument to prevent shell injection.

    Wraps the argument in single quotes and escapes any single quotes
    within the string.

    Args:
        text: String to escape for shell

    Returns:
        str: Shell-escaped string

    Raises:
        TypeError: If text is not a string
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")

    # Replace single quotes with escaped single quotes
    escaped = text.replace("'", "'\\''")

    # Wrap in single quotes
    return f"'{escaped}'"
