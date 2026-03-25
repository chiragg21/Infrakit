"""
infrakit.core.logger.setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Single entry point for configuring infrakit logging.

Call setup() once at application startup. Every module then calls
get_logger(__name__) — no configuration there.

    from infrakit.core.logger import setup, get_logger

    # Files only
    setup(strategy="date_level", stream=None)

    # Stream only
    setup(strategy=None, stream="stdout")

    # Files + stream (most common in prod)
    setup(strategy="date_level", stream="stdout")

    # Isolated session — new subfolder per run
    setup(strategy="date_level", stream="stdout", session=True)
    setup(strategy="date_level", stream="stdout", session="deploy-v1.2.0")

    log = get_logger(__name__)
    log.info("App started")

Env var overrides (take priority over kwargs):
    INFRAKIT_LOG_LEVEL      DEBUG | INFO | WARNING | ERROR | CRITICAL
    INFRAKIT_LOG_FORMAT     human | json
    INFRAKIT_LOG_FILE_FMT   human | json
    INFRAKIT_LOG_STRATEGY   file | date | level | date_level | date_size | None
    INFRAKIT_LOG_STREAM     stdout | stderr | none
    INFRAKIT_LOG_RETENTION  <int days>
    INFRAKIT_LOG_SESSION    <name> | true | false
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from infrakit.core.logger.handlers import FILE_STRATEGIES, build_handlers
from infrakit.core.logger.retention import sweep


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_configured: bool = False
_ROOT_LOGGER = "infrakit"

_VALID_LEVELS  = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_FORMATS = {"human", "json"}

_DEFAULT_LEVEL     = "INFO"
_DEFAULT_FMT       = "human"
_DEFAULT_FILE_FMT  = "json"
_DEFAULT_STRATEGY  = "date_level"
_DEFAULT_STREAM    = "stdout"
_DEFAULT_LOG_DIR   = "logs"
_DEFAULT_RETENTION = 30
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024   # 10 MB


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup(
    *,
    level: str = _DEFAULT_LEVEL,
    fmt: str = _DEFAULT_FMT,
    file_fmt: str = _DEFAULT_FILE_FMT,
    strategy: str | None = _DEFAULT_STRATEGY,
    stream: str | None = _DEFAULT_STREAM,
    log_dir: str | Path = _DEFAULT_LOG_DIR,
    session: bool | str | None = None,
    retention: int = _DEFAULT_RETENTION,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    force: bool = False,
) -> None:
    """Configure infrakit logging. Call once at application startup.

    Parameters
    ----------
    level:
        Minimum log level: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
        ``CRITICAL``. Overridden by ``INFRAKIT_LOG_LEVEL``.
    fmt:
        Format for stream output: ``"human"`` (default) or ``"json"``.
        Overridden by ``INFRAKIT_LOG_FORMAT``.
    file_fmt:
        Format for file output: ``"json"`` (default) or ``"human"``.
        JSON is recommended — easier to parse in log aggregators.
        Overridden by ``INFRAKIT_LOG_FILE_FMT``.
    strategy:
        File storage strategy — controls folder + filename layout:

        ``"file"``        logs/app.log  (size-rotating)
        ``"date"``        logs/app.YYYY-MM-DD.log
        ``"level"``       logs/<level>/<level>.log
        ``"date_level"``  logs/<level>/<level>.YYYY-MM-DD.log
        ``"date_size"``   logs/app.YYYY-MM-DD.log + size cap
        ``None``          no file output

        Overridden by ``INFRAKIT_LOG_STRATEGY``.
    stream:
        Stream to mirror all logs to, independent of strategy:

        ``"stdout"``  write to stdout
        ``"stderr"``  write to stderr
        ``None``      no stream output

        Overridden by ``INFRAKIT_LOG_STREAM``.
    log_dir:
        Base directory for file strategies. Created automatically.
    session:
        Isolate this run in its own subfolder inside *log_dir*:

        ``True``        auto-generate timestamp folder:
                        logs/2025-03-22_14-32-01/
        ``"my-label"``  use named folder:
                        logs/my-label/
        ``None``        no isolation, write directly into log_dir (default)

        Overridden by ``INFRAKIT_LOG_SESSION``.
    retention:
        Days to keep log files. Files older than this are deleted on startup.
        Pass ``0`` to keep all files forever.
        Overridden by ``INFRAKIT_LOG_RETENTION``.
    max_bytes:
        Max file size before rotation (for ``file`` and ``date_size``).
        Default: 10 MB.
    force:
        Tear down existing handlers and reconfigure from scratch.
        Required when calling setup() more than once (e.g. in tests).
    """
    global _configured

    if _configured and not force:
        return

    # --- Resolve env var overrides ---
    level    = _env_str("INFRAKIT_LOG_LEVEL",    level).upper()
    fmt      = _env_str("INFRAKIT_LOG_FORMAT",   fmt)
    file_fmt = _env_str("INFRAKIT_LOG_FILE_FMT", file_fmt)
    retention = _env_int("INFRAKIT_LOG_RETENTION", retention)

    raw_strategy = _env_str("INFRAKIT_LOG_STRATEGY", "" if strategy is None else strategy)
    strategy = None if raw_strategy.lower() in ("none", "") else raw_strategy

    raw_stream = _env_str("INFRAKIT_LOG_STREAM", "" if stream is None else stream)
    stream = None if raw_stream.lower() in ("none", "") else raw_stream

    raw_session = os.environ.get("INFRAKIT_LOG_SESSION", "").strip()
    if raw_session:
        if raw_session.lower() == "true":
            session = True
        elif raw_session.lower() in ("false", "none", ""):
            session = None
        else:
            session = raw_session

    # --- Validate ---
    if level not in _VALID_LEVELS:
        raise ValueError(
            f"Invalid log level '{level}'. "
            f"Choose one of: {', '.join(sorted(_VALID_LEVELS))}"
        )
    if fmt not in _VALID_FORMATS:
        raise ValueError(f"Invalid log format '{fmt}'. Choose 'human' or 'json'.")
    if file_fmt not in _VALID_FORMATS:
        raise ValueError(f"Invalid file_fmt '{file_fmt}'. Choose 'human' or 'json'.")
    if strategy is not None and strategy not in FILE_STRATEGIES:
        raise ValueError(
            f"Invalid strategy '{strategy}'. "
            f"Valid: {', '.join(sorted(FILE_STRATEGIES))} or None."
        )
    if stream not in {None, "stdout", "stderr"}:
        raise ValueError(
            f"Invalid stream '{stream}'. Choose 'stdout', 'stderr', or None."
        )
    if strategy is None and stream is None:
        raise ValueError(
            "At least one of strategy or stream must be set — "
            "otherwise nothing will be logged anywhere."
        )

    numeric_level = getattr(logging, level)
    log_dir = Path(log_dir)

    # --- Resolve session subfolder ---
    resolved_log_dir = _resolve_session_dir(log_dir, session)

    # --- Retention sweep (runs before handlers attach, on root log_dir) ---
    if strategy is not None and retention > 0:
        try:
            sweep(log_dir, retention_days=retention)
        except Exception as exc:
            print(
                f"[infrakit.logger] Retention sweep failed: {exc}",
                file=sys.stderr,
            )

    # --- Configure root logger ---
    root = logging.getLogger(_ROOT_LOGGER)

    if force:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)

    root.setLevel(numeric_level)
    root.propagate = False

    # --- Build and attach handlers ---
    handlers = build_handlers(
        strategy=strategy,
        stream=stream,
        log_dir=resolved_log_dir,
        fmt=fmt,
        file_fmt=file_fmt,
        max_bytes=max_bytes,
        level=numeric_level,
    )
    for h in handlers:
        root.addHandler(h)

    _configured = True

    root.debug(
        "Logger configured: level=%s, fmt=%s, file_fmt=%s, "
        "strategy=%s, stream=%s, log_dir='%s'",
        level, fmt, file_fmt, strategy, stream, resolved_log_dir,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib Logger for *name*.

    Always call as ``get_logger(__name__)``.

    If setup() has not been called, a minimal stderr handler is added
    automatically so logs are never silently swallowed.
    """
    if not _configured:
        _bootstrap()
    return logging.getLogger(name)


def reset() -> None:
    """Tear down all handlers and reset configured state.

    For use in tests only — lets each test start with a clean slate.
    """
    global _configured
    root = logging.getLogger(_ROOT_LOGGER)
    for h in root.handlers[:]:
        h.close()
        root.removeHandler(h)
    _configured = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_session_dir(log_dir: Path, session: bool | str | None) -> Path:
    """Return the effective log directory, incorporating the session subfolder.

    session=None       → log_dir/
    session=True       → log_dir/2025-03-22_14-32-01/
    session="my-run"   → log_dir/my-run/
    """
    if session is None:
        return log_dir
    if session is True:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        return log_dir / ts
    # String label — sanitise to avoid path traversal.
    # Split on both separators, drop any ".." or "." components, rejoin
    # with "-" so "../../evil" becomes "evil" and "../run" becomes "run".
    raw = str(session).replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p not in ("..", ".")]
    safe = "-".join(parts) if parts else "session"
    return log_dir / safe


def _bootstrap() -> None:
    """Minimal fallback — add a WARNING stderr handler if setup() not called."""
    root = logging.getLogger(_ROOT_LOGGER)
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setLevel(logging.WARNING)
        root.addHandler(h)
        root.setLevel(logging.WARNING)


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, "").strip() or default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default