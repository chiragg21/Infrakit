"""
tests/core/logger/test_retention.py
Run with: uv run pytest tests/core/logger/test_retention.py -v
"""
from __future__ import annotations

import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

from infrakit.core.logger.retention import sweep, RetentionResult


def _make_log_file(path: Path, age_days: float) -> Path:
    """Create a log file and backdate its mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("log content")
    mtime = (datetime.now(tz=timezone.utc) - timedelta(days=age_days)).timestamp()
    import os
    os.utime(path, (mtime, mtime))
    return path


class TestSweep:
    def test_deletes_old_files(self, tmp_path):
        old = _make_log_file(tmp_path / "old.log", age_days=40)
        result = sweep(tmp_path, retention_days=30)
        assert not old.exists()
        assert len(result.deleted) == 1

    def test_keeps_recent_files(self, tmp_path):
        recent = _make_log_file(tmp_path / "recent.log", age_days=5)
        result = sweep(tmp_path, retention_days=30)
        assert recent.exists()
        assert len(result.kept) == 1

    def test_deletes_old_keeps_recent(self, tmp_path):
        old    = _make_log_file(tmp_path / "old.log",    age_days=60)
        recent = _make_log_file(tmp_path / "recent.log", age_days=10)
        result = sweep(tmp_path, retention_days=30)
        assert not old.exists()
        assert recent.exists()
        assert result.deleted_count == 1
        assert result.kept_count == 1

    def test_sweeps_subdirectories(self, tmp_path):
        old = _make_log_file(tmp_path / "error" / "error.log", age_days=40)
        result = sweep(tmp_path, retention_days=30)
        assert not old.exists()
        assert result.deleted_count == 1

    def test_dry_run_does_not_delete(self, tmp_path):
        old = _make_log_file(tmp_path / "old.log", age_days=40)
        result = sweep(tmp_path, retention_days=30, dry_run=True)
        assert old.exists()          # file still present
        assert result.deleted_count == 1   # but counted as would-delete

    def test_nonexistent_dir_returns_empty_result(self, tmp_path):
        result = sweep(tmp_path / "nonexistent", retention_days=30)
        assert result.deleted_count == 0
        assert result.kept_count == 0

    def test_negative_retention_raises(self, tmp_path):
        with pytest.raises(ValueError, match="retention_days"):
            sweep(tmp_path, retention_days=-1)

    def test_zero_retention_deletes_all(self, tmp_path):
        f = _make_log_file(tmp_path / "app.log", age_days=0)
        # File is brand new — zero retention means delete everything
        # Backdating to 1 second ago so it's strictly older than cutoff
        import os
        mtime = (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).timestamp()
        os.utime(f, (mtime, mtime))
        result = sweep(tmp_path, retention_days=0)
        assert not f.exists()

    def test_ignores_non_log_files(self, tmp_path):
        non_log = tmp_path / "readme.txt"
        non_log.write_text("not a log")
        import os
        mtime = (datetime.now(tz=timezone.utc) - timedelta(days=60)).timestamp()
        os.utime(non_log, (mtime, mtime))
        result = sweep(tmp_path, retention_days=30)
        assert non_log.exists()
        assert result.deleted_count == 0

    def test_result_str_readable(self, tmp_path):
        _make_log_file(tmp_path / "old.log", age_days=40)
        result = sweep(tmp_path, retention_days=30)
        assert "Deleted" in str(result)

    def test_rotation_backup_files_deleted(self, tmp_path):
        # app.log.1, app.log.2 are rotation backups — should be swept
        for i in (1, 2):
            _make_log_file(tmp_path / f"app.log.{i}", age_days=40)
        result = sweep(tmp_path, retention_days=30)
        assert result.deleted_count == 2