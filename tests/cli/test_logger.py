"""
tests/cli/test_logger.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for ``ik logger check`` and ``ik logger clean``.

retention.sweep() only deletes files matching *.log patterns — test fixtures
must use .log extensions or files won't be picked up.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def log_dir(tmp_path):
    """
    A logs directory with:
      - today.log   — fresh, must never be deleted
      - old.log     — mtime set 10 days ago, should be deleted with --days 7
    """
    d = tmp_path / "logs"
    d.mkdir()

    fresh = d / "today.log"
    fresh.write_text("fresh log\n")

    old = d / "old.log"
    old.write_text("old log\n")
    old_mtime = time.time() - (10 * 86400)
    os.utime(old, (old_mtime, old_mtime))

    return d


# ══════════════════════════════════════════════════════════════════════════════
# logger check
# ══════════════════════════════════════════════════════════════════════════════

class TestLoggerCheck:

    def test_exits_zero(self, cli):
        result = cli(["logger", "check"])
        assert result.exit_code == 0

    def test_shows_all_expected_labels(self, cli):
        result = cli(["logger", "check"])
        for label in ("log_dir", "strategy", "stream", "format", "level",
                      "session", "retention_days", "dry_run"):
            assert label in result.output

    def test_no_env_vars_shows_defaults(self, cli):
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("INFRAKIT_LOG_")}
        with patch.dict(os.environ, clean_env, clear=True):
            result = cli(["logger", "check"])
        assert result.exit_code == 0
        assert "default" in result.output

    def test_set_env_var_appears_in_output(self, cli):
        with patch.dict(os.environ, {"INFRAKIT_LOG_LEVEL": "WARNING"}):
            result = cli(["logger", "check"])
        assert result.exit_code == 0
        assert "WARNING" in result.output

    def test_multiple_env_vars_all_shown(self, cli):
        with patch.dict(os.environ, {
            "INFRAKIT_LOG_LEVEL":    "ERROR",
            "INFRAKIT_LOG_STRATEGY": "date_level",
            "INFRAKIT_LOG_DIR":      "/tmp/logs",
        }):
            result = cli(["logger", "check"])
        assert "ERROR"      in result.output
        assert "date_level" in result.output
        assert "/tmp/logs"  in result.output


# ══════════════════════════════════════════════════════════════════════════════
# logger clean
# ══════════════════════════════════════════════════════════════════════════════

class TestLoggerClean:

    def test_no_old_files_exits_zero(self, cli, log_dir):
        # --days 11: the 10-day-old file does not qualify, so nothing to delete
        result = cli(["logger", "clean", str(log_dir), "--days", "11", "--no-confirm"])
        assert result.exit_code == 0
        assert "No log files" in result.output

    def test_deletes_old_file(self, cli, log_dir):
        old_file = log_dir / "old.log"
        assert old_file.exists()
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--no-confirm"])
        assert result.exit_code == 0
        assert not old_file.exists()

    def test_preserves_fresh_file(self, cli, log_dir):
        fresh_file = log_dir / "today.log"
        cli(["logger", "clean", str(log_dir), "--days", "7", "--no-confirm"])
        assert fresh_file.exists()

    def test_dry_run_does_not_delete(self, cli, log_dir):
        old_file = log_dir / "old.log"
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--dry-run"])
        assert result.exit_code == 0
        assert old_file.exists()

    def test_dry_run_lists_files(self, cli, log_dir):
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--dry-run"])
        assert "old.log" in result.output

    def test_dry_run_shows_dry_run_message(self, cli, log_dir):
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--dry-run"])
        assert "dry" in result.output.lower()

    def test_success_message_shows_count(self, cli, log_dir):
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--no-confirm"])
        assert "Deleted" in result.output
        assert "1" in result.output

    def test_shows_found_files_before_delete(self, cli, log_dir):
        result = cli(["logger", "clean", str(log_dir), "--days", "7", "--no-confirm"])
        assert "old.log" in result.output

    def test_missing_dir_exits_nonzero(self, cli, tmp_path):
        result = cli(["logger", "clean", str(tmp_path / "nope"), "--days", "7"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_days_less_than_one_exits_nonzero(self, cli, log_dir):
        result = cli(["logger", "clean", str(log_dir), "--days", "0"])
        assert result.exit_code != 0

    def test_missing_days_flag_exits_nonzero(self, cli, log_dir):
        """--days is required."""
        result = cli(["logger", "clean", str(log_dir)])
        assert result.exit_code != 0

    def test_non_log_files_not_deleted(self, cli, log_dir):
        """sweep() only touches *.log files — other files must be untouched."""
        non_log = log_dir / "notes.txt"
        non_log.write_text("keep me\n")
        old_mtime = time.time() - (10 * 86400)
        os.utime(non_log, (old_mtime, old_mtime))
        cli(["logger", "clean", str(log_dir), "--days", "7", "--no-confirm"])
        assert non_log.exists()