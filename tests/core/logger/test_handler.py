"""
tests/core/logger/test_handlers.py
"""
from __future__ import annotations

import logging
import sys
import pytest
from pathlib import Path

from infrakit.core.logger.handlers import (
    FILE_STRATEGIES, build_handlers, _ExactLevelFilter,
)


class TestBuildHandlersStream:
    def test_stdout_only(self):
        handlers = build_handlers(strategy=None, stream="stdout", log_dir=Path("."))
        assert len(handlers) == 1
        assert handlers[0].stream is sys.stdout

    def test_stderr_only(self):
        handlers = build_handlers(strategy=None, stream="stderr", log_dir=Path("."))
        assert handlers[0].stream is sys.stderr

    def test_no_stream_no_strategy_raises(self):
        # build_handlers itself doesn't raise — setup() catches this.
        # With strategy=None and stream=None it just returns empty list.
        handlers = build_handlers(strategy=None, stream=None, log_dir=Path("."))
        assert handlers == []

    def test_invalid_stream_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown stream"):
            build_handlers(strategy=None, stream="syslog", log_dir=tmp_path)

    def test_invalid_strategy_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown file strategy"):
            build_handlers(strategy="weekly", stream=None, log_dir=tmp_path)


class TestBuildHandlersFileStrategies:
    def test_file_creates_app_log(self, tmp_path):
        build_handlers(strategy="file", stream=None, log_dir=tmp_path)
        assert (tmp_path / "app.log").exists()

    def test_date_creates_dated_file(self, tmp_path):
        build_handlers(strategy="date", stream=None, log_dir=tmp_path)
        import re
        logs = list(tmp_path.glob("app.*.log"))
        assert len(logs) == 1
        assert re.search(r"\d{4}-\d{2}-\d{2}", logs[0].name)

    def test_level_creates_subfolders(self, tmp_path):
        build_handlers(strategy="level", stream=None, log_dir=tmp_path)
        for name in ("info", "warning", "error"):
            assert (tmp_path / name).is_dir()

    def test_level_one_file_per_level(self, tmp_path):
        build_handlers(strategy="level", stream=None, log_dir=tmp_path)
        for name in ("info", "warning", "error"):
            assert len(list((tmp_path / name).glob("*.log"))) == 1

    def test_date_level_dated_files_in_subfolders(self, tmp_path):
        import re
        build_handlers(strategy="date_level", stream=None, log_dir=tmp_path)
        for name in ("info", "warning", "error"):
            logs = list((tmp_path / name).glob("*.log"))
            assert len(logs) == 1
            assert re.search(r"\d{4}-\d{2}-\d{2}", logs[0].name)

    def test_date_size_creates_dated_file(self, tmp_path):
        build_handlers(strategy="date_size", stream=None, log_dir=tmp_path)
        assert len(list(tmp_path.glob("app.*.log"))) == 1

    def test_all_file_strategies_accepted(self, tmp_path):
        for strategy in FILE_STRATEGIES:
            handlers = build_handlers(
                strategy=strategy, stream=None, log_dir=tmp_path / strategy
            )
            assert isinstance(handlers, list)
            assert len(handlers) >= 1


class TestBuildHandlersComposed:
    def test_date_level_plus_stdout(self, tmp_path):
        handlers = build_handlers(
            strategy="date_level", stream="stdout", log_dir=tmp_path
        )
        # stream handler + one per level
        stream_handlers = [h for h in handlers if type(h) is logging.StreamHandler]
        assert any(h.stream is sys.stdout for h in stream_handlers)
        assert len(handlers) > 1

    def test_date_level_plus_stderr(self, tmp_path):
        handlers = build_handlers(
            strategy="date_level", stream="stderr", log_dir=tmp_path
        )
        stream_handlers = [h for h in handlers if type(h) is logging.StreamHandler]
        assert any(h.stream is sys.stderr for h in stream_handlers)

    def test_level_plus_stdout_creates_subfolders_and_stream(self, tmp_path):
        handlers = build_handlers(
            strategy="level", stream="stdout", log_dir=tmp_path
        )
        assert (tmp_path / "info").is_dir()
        assert any(
            hasattr(h, 'stream') and h.stream is sys.stdout
            for h in handlers
        )

    def test_file_plus_stderr(self, tmp_path):
        handlers = build_handlers(
            strategy="file", stream="stderr", log_dir=tmp_path
        )
        assert len(handlers) == 2
        assert (tmp_path / "app.log").exists()

    def test_date_plus_stdout(self, tmp_path):
        handlers = build_handlers(
            strategy="date", stream="stdout", log_dir=tmp_path
        )
        assert len(handlers) == 2

    def test_date_size_plus_stderr(self, tmp_path):
        handlers = build_handlers(
            strategy="date_size", stream="stderr", log_dir=tmp_path
        )
        assert len(handlers) == 2


class TestLevelFiltering:
    def test_level_strategy_skips_below_minimum(self, tmp_path):
        # With level=WARNING, only warning and error files should be created
        build_handlers(
            strategy="level", stream=None,
            log_dir=tmp_path, level=logging.WARNING,
        )
        assert not (tmp_path / "debug").exists()
        assert not (tmp_path / "info").exists()
        assert (tmp_path / "warning").exists()
        assert (tmp_path / "error").exists()


class TestExactLevelFilter:
    def test_passes_exact_level(self):
        f = _ExactLevelFilter(logging.WARNING)
        r = logging.LogRecord("x", logging.WARNING, "", 0, "", (), None)
        assert f.filter(r) is True

    def test_rejects_above(self):
        f = _ExactLevelFilter(logging.WARNING)
        r = logging.LogRecord("x", logging.ERROR, "", 0, "", (), None)
        assert f.filter(r) is False

    def test_rejects_below(self):
        f = _ExactLevelFilter(logging.WARNING)
        r = logging.LogRecord("x", logging.INFO, "", 0, "", (), None)
        assert f.filter(r) is False