"""
tests/core/logger/test_setup.py
"""
from __future__ import annotations

import logging
import sys
import pytest

from infrakit.core.logger import setup, get_logger, reset


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


class TestSetupBasic:
    def test_stream_only(self, tmp_path):
        setup(strategy=None, stream="stdout", log_dir=tmp_path)

    def test_file_only(self, tmp_path):
        setup(strategy="file", stream=None, log_dir=tmp_path)
        assert (tmp_path / "app.log").exists()

    def test_both_strategy_and_stream(self, tmp_path):
        setup(strategy="date_level", stream="stdout", log_dir=tmp_path)
        root = logging.getLogger("infrakit")
        assert len(root.handlers) > 1

    def test_idempotent(self, tmp_path):
        setup(strategy=None, stream="stdout", log_dir=tmp_path)
        setup(strategy=None, stream="stdout", log_dir=tmp_path)
        root = logging.getLogger("infrakit")
        assert len(root.handlers) == 1

    def test_force_reconfigures(self, tmp_path):
        setup(strategy=None, stream="stdout", log_dir=tmp_path)
        setup(strategy=None, stream="stderr", log_dir=tmp_path, force=True)
        root = logging.getLogger("infrakit")
        assert root.handlers[0].stream is sys.stderr

    def test_no_propagation(self, tmp_path):
        setup(strategy=None, stream="stdout", log_dir=tmp_path)
        assert logging.getLogger("infrakit").propagate is False

    def test_level_applied(self, tmp_path):
        setup(level="DEBUG", strategy=None, stream="stdout", log_dir=tmp_path)
        assert logging.getLogger("infrakit").level == logging.DEBUG


class TestSetupValidation:
    def test_invalid_level_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid log level"):
            setup(level="VERBOSE", stream="stdout", log_dir=tmp_path)

    def test_invalid_fmt_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid log format"):
            setup(fmt="pretty", stream="stdout", log_dir=tmp_path)

    def test_invalid_strategy_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid strategy"):
            setup(strategy="weekly", stream="stdout", log_dir=tmp_path)

    def test_invalid_stream_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid stream"):
            setup(strategy=None, stream="syslog", log_dir=tmp_path)

    def test_both_none_raises(self, tmp_path):
        with pytest.raises(ValueError, match="At least one"):
            setup(strategy=None, stream=None, log_dir=tmp_path)


class TestSetupSession:
    def test_session_true_creates_timestamp_folder(self, tmp_path):
        import re
        setup(strategy="file", stream=None, log_dir=tmp_path, session=True)
        subfolders = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(subfolders) == 1
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", subfolders[0].name)

    def test_session_string_creates_named_folder(self, tmp_path):
        setup(strategy="file", stream=None, log_dir=tmp_path, session="deploy-v1.2")
        assert (tmp_path / "deploy-v1.2").is_dir()

    def test_session_none_writes_directly_to_log_dir(self, tmp_path):
        setup(strategy="file", stream=None, log_dir=tmp_path, session=None)
        assert (tmp_path / "app.log").exists()

    def test_two_sessions_create_two_folders(self, tmp_path):
        setup(strategy="file", stream=None, log_dir=tmp_path, session="run-1")
        reset()
        setup(strategy="file", stream=None, log_dir=tmp_path, session="run-2", force=True)
        sessions = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(sessions) == 2

    def test_session_path_traversal_sanitised(self, tmp_path):
        setup(strategy="file", stream=None, log_dir=tmp_path, session="../evil")
        # Check only the created folder NAME, not the full absolute path.
        # The full path naturally contains ".." in Windows temp dir segments.
        folders = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(folders) == 1
        assert ".." not in folders[0].name


class TestEnvOverrides:
    def test_level_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_LEVEL", "DEBUG")
        setup(level="INFO", stream="stdout", log_dir=tmp_path)
        assert logging.getLogger("infrakit").level == logging.DEBUG

    def test_format_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_FORMAT", "json")
        setup(fmt="human", stream="stdout", log_dir=tmp_path)
        from infrakit.core.logger.formatters import JsonFormatter
        root = logging.getLogger("infrakit")
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_strategy_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_STRATEGY", "file")
        setup(strategy="date", stream=None, log_dir=tmp_path)
        assert (tmp_path / "app.log").exists()

    def test_stream_override_to_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_STREAM", "none")
        setup(strategy="file", stream="stdout", log_dir=tmp_path)
        root = logging.getLogger("infrakit")
        # RotatingFileHandler inherits .stream from StreamHandler so
        # hasattr(h, "stream") is True for file handlers too.
        # Check the concrete type instead.
        pure_stream = [
            h for h in root.handlers
            if type(h) is logging.StreamHandler
        ]
        assert len(pure_stream) == 0

    def test_session_override_true(self, tmp_path, monkeypatch):
        import re
        monkeypatch.setenv("INFRAKIT_LOG_SESSION", "true")
        setup(strategy="file", stream=None, log_dir=tmp_path)
        subfolders = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(subfolders) == 1
        assert re.match(r"\d{4}-\d{2}-\d{2}_", subfolders[0].name)

    def test_session_override_named(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_SESSION", "ci-run")
        setup(strategy="file", stream=None, log_dir=tmp_path)
        assert (tmp_path / "ci-run").is_dir()

    def test_invalid_retention_env_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFRAKIT_LOG_RETENTION", "notanumber")
        setup(stream="stdout", log_dir=tmp_path)   # should not raise


class TestGetLogger:
    def test_returns_stdlib_logger(self, tmp_path):
        setup(stream="stdout", log_dir=tmp_path)
        log = get_logger("infrakit.test")
        assert isinstance(log, logging.Logger)

    def test_name_preserved(self, tmp_path):
        setup(stream="stdout", log_dir=tmp_path)
        assert get_logger("infrakit.config.loader").name == "infrakit.config.loader"

    def test_before_setup_adds_bootstrap(self):
        log = get_logger("infrakit.test")
        root = logging.getLogger("infrakit")
        assert len(root.handlers) >= 1


class TestReset:
    def test_clears_handlers(self, tmp_path):
        setup(stream="stdout", log_dir=tmp_path)
        reset()
        assert logging.getLogger("infrakit").handlers == []

    def test_setup_works_after_reset(self, tmp_path):
        setup(stream="stdout", log_dir=tmp_path)
        reset()
        setup(stream="stderr", log_dir=tmp_path)
        root = logging.getLogger("infrakit")
        assert root.handlers[0].stream is sys.stderr