"""Tests for the owner-only secret file writer (F-03)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from penguin_email._fileio import write_secret_file


class TestWriteSecretFile:
    def test_new_file_is_mode_0600(self, tmp_path: Path) -> None:
        target = tmp_path / "token.json"
        write_secret_file(str(target), '{"a": 1}')
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
        assert target.read_text() == '{"a": 1}'

    def test_existing_world_readable_file_is_tightened(self, tmp_path: Path) -> None:
        target = tmp_path / "token.json"
        target.write_text("old")
        os.chmod(target, 0o666)
        write_secret_file(str(target), "new")
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
        assert target.read_text() == "new"

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        write_secret_file(str(tmp_path / "token.json"), "x")
        assert sorted(p.name for p in tmp_path.iterdir()) == ["token.json"]

    def test_failed_write_keeps_original_and_removes_temp(self, tmp_path: Path) -> None:
        target = tmp_path / "token.json"
        target.write_text("original")
        with pytest.raises(TypeError):
            write_secret_file(str(target), 12345)  # type: ignore[arg-type]
        assert target.read_text() == "original"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["token.json"]
