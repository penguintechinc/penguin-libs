"""Owner-only file writes for secrets such as OAuth tokens."""

from __future__ import annotations

import contextlib
import os
import tempfile


def write_secret_file(path: str, content: str) -> None:
    """Atomically write *content* to *path* with mode ``0o600``.

    The data goes to a temporary file in the same directory (created with
    ``0o600`` regardless of umask), is fsync'd, then renamed over *path*.
    This tightens permissions on a pre-existing file and never leaves a
    partially written or world-readable token behind.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise
