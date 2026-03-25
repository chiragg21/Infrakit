"""
infrakit.core.logger.handlers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Maps a strategy + stream combination to a list of configured handlers.

File strategies control folder structure:
    file          logs/app.log
    date          logs/app.2025-03-22.log
    level         logs/debug/debug.log
                  logs/info/info.log
                  logs/warning/warning.log
                  logs/error/error.log
    date_level    logs/debug/debug.2025-03-22.log
                  logs/info/info.2025-03-22.log
                  logs/warning/warning.2025-03-22.log
                  logs/error/error.2025-03-22.log
    date_size     logs/app.2025-03-22.log  (+ rotates at max_bytes)

stream= adds a stream handler on top of any file strategy:
    stream="stdout"   also write to stdout
    stream="stderr"   also write to stderr
    stream=None       no stream output (default)

Stream-only (no files):
    strategy=None, stream="stdout"
    strategy=None, stream="stderr"

Session isolation:
    log_dir is already resolved by setup() before build_handlers() is called.
    Handlers just write to whatever log_dir they receive.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infrakit.core.logger.formatters import HumanFormatter, JsonFormatter


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

FILE_STRATEGIES = {
    "file",
    "date",
    "level",
    "date_level",
    "date_size",
}

STREAM_OPTIONS = {"stdout", "stderr", None}

_FILE_LEVELS = [
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
]

_DEFAULT_MAX_BYTES    = 10 * 1024 * 1024   # 10 MB
_DEFAULT_BACKUP_COUNT = 5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_handlers(
    *,
    strategy: str | None,
    stream: str | None,
    log_dir: Path,
    fmt: str = "human",
    file_fmt: str = "json",
    max_bytes: int = _DEFAULT_MAX_BYTES,
    level: int = logging.DEBUG,
) -> list[logging.Handler]:
    """Return a configured list of handlers.

    Parameters
    ----------
    strategy:
        File storage strategy — one of FILE_STRATEGIES, or None for no files.
    stream:
        Stream to mirror logs to: ``"stdout"``, ``"stderr"``, or ``None``.
    log_dir:
        Resolved base directory (already includes session subfolder if any).
        Created automatically for file strategies.
    fmt:
        Formatter for stream output — ``"human"`` or ``"json"``.
    file_fmt:
        Formatter for file output — ``"json"`` or ``"human"``.
    max_bytes:
        Max file size before rotation (``file`` and ``date_size``).
    level:
        Minimum level all handlers accept.

    Returns
    -------
    list[logging.Handler]

    Raises
    ------
    ValueError
        If *strategy* or *stream* is not a recognised value.
    """
    if strategy is not None and strategy not in FILE_STRATEGIES:
        raise ValueError(
            f"Unknown file strategy '{strategy}'. "
            f"Valid strategies: {', '.join(sorted(FILE_STRATEGIES))} or None."
        )
    if stream not in STREAM_OPTIONS:
        raise ValueError(
            f"Unknown stream '{stream}'. Valid options: 'stdout', 'stderr', None."
        )

    stream_formatter = _make_formatter(fmt, is_stream=True)
    file_formatter   = _make_formatter(file_fmt, is_stream=False)

    handlers: list[logging.Handler] = []

    # --- Stream handler (independent of file strategy) ---
    if stream == "stdout":
        handlers.append(_stream_handler(sys.stdout, stream_formatter, level))
    elif stream == "stderr":
        handlers.append(_stream_handler(sys.stderr, stream_formatter, level))

    # --- File handlers ---
    if strategy is None:
        pass

    elif strategy == "file":
        _ensure_dir(log_dir)
        handlers.append(_rotating_handler(
            log_dir / "app.log", file_formatter, level, max_bytes,
        ))

    elif strategy == "date":
        _ensure_dir(log_dir)
        handlers.append(_timed_handler(
            log_dir / _dated_name("app"), file_formatter, level,
        ))

    elif strategy == "level":
        handlers.extend(_level_handlers(
            log_dir, file_formatter,
            dated=False, max_bytes=max_bytes, level=level,
        ))

    elif strategy == "date_level":
        handlers.extend(_level_handlers(
            log_dir, file_formatter,
            dated=True, max_bytes=max_bytes, level=level,
        ))

    elif strategy == "date_size":
        _ensure_dir(log_dir)
        handlers.append(_timed_size_handler(
            log_dir / _dated_name("app"), file_formatter, level, max_bytes,
        ))

    return handlers


# ---------------------------------------------------------------------------
# Handler factories
# ---------------------------------------------------------------------------

def _stream_handler(
    stream: Any,
    formatter: logging.Formatter,
    level: int,
) -> logging.StreamHandler:
    h = logging.StreamHandler(stream)
    h.setFormatter(formatter)
    h.setLevel(level)
    return h


def _rotating_handler(
    path: Path,
    formatter: logging.Formatter,
    level: int,
    max_bytes: int,
) -> logging.handlers.RotatingFileHandler:
    _ensure_dir(path.parent)
    h = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=_DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    h.setFormatter(formatter)
    h.setLevel(level)
    return h


def _timed_handler(
    path: Path,
    formatter: logging.Formatter,
    level: int,
) -> logging.handlers.TimedRotatingFileHandler:
    _ensure_dir(path.parent)
    h = logging.handlers.TimedRotatingFileHandler(
        path,
        when="midnight",
        backupCount=_DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    h.setFormatter(formatter)
    h.setLevel(level)
    return h


def _timed_size_handler(
    path: Path,
    formatter: logging.Formatter,
    level: int,
    max_bytes: int,
) -> logging.handlers.RotatingFileHandler:
    """Size-rotating handler on a date-named file.

    Python stdlib has no combined timed+size handler. We use RotatingFileHandler
    on a file whose name contains today's date — a new file is used each day
    naturally, and within a day size rotation handles overflow.
    """
    _ensure_dir(path.parent)
    h = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=_DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    h.setFormatter(formatter)
    h.setLevel(level)
    return h


def _level_handlers(
    log_dir: Path,
    formatter: logging.Formatter,
    *,
    dated: bool,
    max_bytes: int,
    level: int,
) -> list[logging.Handler]:
    """One handler per level, each in its own subfolder.

    Folder layout:
        logs/debug/debug.log                (dated=False)
        logs/debug/debug.2025-03-22.log     (dated=True)

    Each handler has an _ExactLevelFilter — only records at that exact
    level are written. WARNING never appears in info.log.
    Levels below the configured minimum are skipped entirely.
    """
    handlers: list[logging.Handler] = []

    for lvl in _FILE_LEVELS:
        if lvl < level:
            continue

        level_name = logging.getLevelName(lvl).lower()
        level_dir  = log_dir / level_name
        _ensure_dir(level_dir)

        filename = _dated_name(level_name) if dated else f"{level_name}.log"
        path = level_dir / filename

        h = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=_DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        )
        h.setFormatter(formatter)
        h.setLevel(lvl)
        h.addFilter(_ExactLevelFilter(lvl))
        handlers.append(h)

    return handlers


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class _ExactLevelFilter(logging.Filter):
    """Pass only records at exactly *level* — not above, not below."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_formatter(fmt: str, *, is_stream: bool) -> logging.Formatter:
    if fmt == "json":
        return JsonFormatter()
    return HumanFormatter(use_colour=is_stream)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _dated_name(stem: str) -> str:
    """Return 'stem.YYYY-MM-DD.log' for today's UTC date."""
    date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return f"{stem}.{date}.log"