"""HTML sanitization and XSS prevention utilities."""

import html
import re
from typing import Any


def sanitize_html(text: str) -> str:
    """
    Sanitize HTML to prevent XSS attacks.

    Removes:
    - Script tags (but extracts and cleans their text content)
    - Event handlers (onclick, onerror, onload, etc.)
    - JavaScript URLs (javascript:)
    - Data URLs with scripts
    - Null bytes
    - SVG-based XSS vectors

    Args:
        text: HTML string to sanitize

    Returns:
        str: Sanitized HTML string with harmful tags removed

    Raises:
        TypeError: If text is not a string
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")

    # Remove null bytes
    text = text.replace("\x00", "")

    # Remove script tags but try to preserve text content for non-dangerous scripts
    # Pattern: extract content between script tags, then remove the tags entirely if it contains dangerous code
    def sanitize_script_tag(match):
        content = match.group(1)
        # Remove dangerous JavaScript functions/patterns
        dangerous_patterns = [
            r'alert\s*\(',
            r'confirm\s*\(',
            r'prompt\s*\(',
            r'eval\s*\(',
            r'Function\s*\(',
            r'fetch\s*\(',
            r'XMLHttpRequest',
            r'WebSocket',
        ]
        # If content contains any dangerous patterns, remove entirely
        for pattern in dangerous_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return ''
        # Otherwise preserve the content (it might be data or safe text)
        return content

    text = re.sub(r"<script[^>]*>(.*?)</script>", sanitize_script_tag, text, flags=re.IGNORECASE | re.DOTALL)

    # Remove event handlers (onclick, onerror, onload, etc.)
    text = re.sub(r'\s+on\w+\s*=\s*["\']?[^"\'>\s]*["\']?', "", text, flags=re.IGNORECASE)

    # Remove javascript: URLs
    text = re.sub(r'javascript:', "", text, flags=re.IGNORECASE)

    # Remove data: URLs that might contain scripts
    text = re.sub(r'data:text/html[^,]*,', "", text, flags=re.IGNORECASE)

    # Remove SVG with onload/onerror and their content
    text = re.sub(r"<svg[^>]*>.*?</svg>", "", text, flags=re.IGNORECASE | re.DOTALL)

    # Remove iframe, embed, object tags and their content
    text = re.sub(r"<(iframe|embed|object)[^>]*>.*?</\1>", "", text, flags=re.IGNORECASE | re.DOTALL)

    return text


def escape_sql_string(text: str) -> str:
    """
    Escape SQL string to prevent SQL injection.

    Note: This is a basic escaping function. For production, use
    parameterized queries instead.

    Args:
        text: String to escape

    Returns:
        str: Escaped SQL string

    Raises:
        TypeError: If text is not a string
    """
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
    """
    Escape shell argument to prevent shell injection.

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
