"""
infrakit.core.logger.formatters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Two formatters — HumanFormatter for dev, JsonFormatter for prod/aggregators.

HumanFormatter output:
    2025-03-22 14:32:01 | INFO     | infrakit.config.loader | Config loaded

JsonFormatter output:
    {"timestamp": "2025-03-22T14:32:01Z", "level": "INFO",
     "logger": "infrakit.config.loader", "message": "Config loaded"}
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Human formatter
# ---------------------------------------------------------------------------

class HumanFormatter(logging.Formatter):
    """Coloured, pipe-delimited single-line format for terminal output.

    Columns are padded so they align vertically across log lines:
        TIMESTAMP           | LEVEL     | LOGGER (truncated)      | MESSAGE
        2025-03-22 14:32:01 | INFO      | infrakit.config.loader  | ...
    """

    # Pad level name to this width so columns stay aligned
    _LEVEL_WIDTH = 8

    # Truncate logger name to this width (right side kept — most specific part)
    _LOGGER_WIDTH = 24

    # ANSI colour codes — only applied to stream handlers (TTY)
    _COLOURS = {
        "DEBUG":    "\033[36m",    # cyan
        "INFO":     "\033[32m",    # green
        "WARNING":  "\033[33m",    # yellow
        "ERROR":    "\033[31m",    # red
        "CRITICAL": "\033[35m",    # magenta
    }
    _RESET = "\033[0m"

    def __init__(self, *, use_colour: bool = False) -> None:
        super().__init__()
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        level = record.levelname.ljust(self._LEVEL_WIDTH)
        logger = _truncate_left(record.name, self._LOGGER_WIDTH).ljust(self._LOGGER_WIDTH)
        message = record.getMessage()

        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        if self.use_colour:
            colour = self._COLOURS.get(record.levelname, "")
            level = f"{colour}{level}{self._RESET}"

        return f"{ts} | {level} | {logger} | {message}"


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Newline-delimited JSON — one object per log record.

    Always-present fields:
        timestamp, level, logger, message

    Optional fields (only present when relevant):
        exc_type, exc_message, exc_traceback  — when exc_info is set
        extra.*                               — any extra={} keys on the record
    """

    # Keys that live on every LogRecord — exclude from the "extra" sweep
    _STDLIB_ATTRS = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        record.getMessage()   # populate record.message

        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # Exception info
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exc_type"]      = exc_type.__name__
            payload["exc_message"]   = str(exc_value)
            payload["exc_traceback"] = "".join(
                traceback.format_tb(exc_tb)
            ).strip()

        # Extra fields attached via log.info("msg", extra={"key": "val"})
        for key, value in record.__dict__.items():
            if key not in self._STDLIB_ATTRS and not key.startswith("_"):
                try:
                    json.dumps(value)   # check it's serialisable
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_left(s: str, width: int) -> str:
    """Keep the rightmost *width* chars of *s*, prefixing '…' if truncated.

    Used for logger names so the most specific part (e.g. 'loader') is always
    visible even when the full dotted path is long.

        "infrakit.core.config.loader" (28) → "…infrakit.core.config.load" (25)
    """
    if len(s) <= width:
        return s
    return "\u2026" + s[-(width - 1):]