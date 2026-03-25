"""
tests/core/logger/test_formatters.py
Run with: uv run pytest tests/core/logger/test_formatters.py -v
"""
from __future__ import annotations

import json
import logging
import time
import pytest

from infrakit.core.logger.formatters import HumanFormatter, JsonFormatter, _truncate_left


def _make_record(
    msg: str = "test message",
    level: int = logging.INFO,
    name: str = "infrakit.test",
    exc_info=None,
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name, level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=exc_info,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# HumanFormatter
# ---------------------------------------------------------------------------

class TestHumanFormatter:
    def test_contains_message(self):
        fmt = HumanFormatter()
        record = _make_record("hello world")
        assert "hello world" in fmt.format(record)

    def test_contains_level(self):
        fmt = HumanFormatter()
        record = _make_record(level=logging.WARNING)
        assert "WARNING" in fmt.format(record)

    def test_contains_logger_name(self):
        fmt = HumanFormatter()
        record = _make_record(name="infrakit.config.loader")
        output = fmt.format(record)
        # Full name may be truncated — rightmost part must be visible
        assert "loader" in output

    def test_pipe_delimiters(self):
        fmt = HumanFormatter()
        output = fmt.format(_make_record())
        assert output.count("|") >= 3

    def test_timestamp_format(self):
        fmt = HumanFormatter()
        output = fmt.format(_make_record())
        # Should match YYYY-MM-DD HH:MM:SS
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", output)

    def test_exc_info_appended(self):
        fmt = HumanFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = _make_record(exc_info=sys.exc_info())
        output = fmt.format(record)
        assert "ValueError" in output
        assert "boom" in output

    def test_no_colour_by_default(self):
        fmt = HumanFormatter()
        output = fmt.format(_make_record())
        assert "\033[" not in output

    def test_colour_when_enabled(self):
        fmt = HumanFormatter(use_colour=True)
        output = fmt.format(_make_record(level=logging.ERROR))
        assert "\033[" in output


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_valid_json(self):
        fmt = JsonFormatter()
        output = fmt.format(_make_record())
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        fmt = JsonFormatter()
        parsed = json.loads(fmt.format(_make_record()))
        for field in ("timestamp", "level", "logger", "message"):
            assert field in parsed

    def test_message_correct(self):
        fmt = JsonFormatter()
        parsed = json.loads(fmt.format(_make_record("hello")))
        assert parsed["message"] == "hello"

    def test_level_correct(self):
        fmt = JsonFormatter()
        parsed = json.loads(fmt.format(_make_record(level=logging.ERROR)))
        assert parsed["level"] == "ERROR"

    def test_logger_correct(self):
        fmt = JsonFormatter()
        parsed = json.loads(fmt.format(_make_record(name="infrakit.llm")))
        assert parsed["logger"] == "infrakit.llm"

    def test_timestamp_utc_format(self):
        fmt = JsonFormatter()
        parsed = json.loads(fmt.format(_make_record()))
        ts = parsed["timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_exc_info_fields(self):
        fmt = JsonFormatter()
        try:
            raise RuntimeError("exploded")
        except RuntimeError:
            import sys
            record = _make_record(exc_info=sys.exc_info())
        parsed = json.loads(fmt.format(record))
        assert parsed["exc_type"] == "RuntimeError"
        assert "exploded" in parsed["exc_message"]
        assert "exc_traceback" in parsed

    def test_extra_fields_included(self):
        fmt = JsonFormatter()
        record = _make_record(extra={"request_id": "abc123"})
        parsed = json.loads(fmt.format(record))
        assert parsed.get("request_id") == "abc123"

    def test_non_serialisable_extra_repr(self):
        fmt = JsonFormatter()
        record = _make_record(extra={"obj": object()})
        parsed = json.loads(fmt.format(record))
        assert "obj" in parsed   # repr fallback — still included


# ---------------------------------------------------------------------------
# _truncate_left helper
# ---------------------------------------------------------------------------

class TestTruncateLeft:
    def test_short_string_unchanged(self):
        assert _truncate_left("abc", 10) == "abc"

    def test_exact_length_unchanged(self):
        assert _truncate_left("abcde", 5) == "abcde"

    def test_long_string_truncated(self):
        result = _truncate_left("infrakit.core.config.loader", 15)
        assert len(result) == 15
        assert result.startswith("\u2026")

    def test_rightmost_content_kept(self):
        result = _truncate_left("infrakit.core.config.loader", 10)
        assert "loader" in result