"""
infrakit.core.logger.retention
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sweep the log directory on startup and delete files older than N days.

Retention runs once inside setup() — not on every log write.
Each storage strategy produces a different folder layout; the sweeper
handles all of them by walking the entire log_dir tree.

Deletion rules:
  - Only files matching known log patterns are deleted (*.log, *.log.*)
  - Folders are never deleted, even if empty after sweep
  - Files modified within the retention window are always kept
  - Dry-run mode returns what would be deleted without touching anything
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


log = logging.getLogger(__name__)

# Suffixes considered log files — anything else is left alone
_LOG_SUFFIXES = {".log"}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class RetentionResult:
    """Summary of a retention sweep."""
    deleted: list[Path]
    kept: list[Path]
    errors: list[tuple[Path, Exception]]

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    def __str__(self) -> str:
        parts = [f"Deleted {self.deleted_count} file(s), kept {self.kept_count}."]
        if self.errors:
            parts.append(f"{len(self.errors)} error(s) during sweep.")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sweep(
    log_dir: str | Path,
    *,
    retention_days: int,
    dry_run: bool = False,
) -> RetentionResult:
    """Delete log files in *log_dir* older than *retention_days* days.

    Parameters
    ----------
    log_dir:
        Root directory to sweep. All subdirectories are included.
    retention_days:
        Files whose last-modified time is older than this are deleted.
        Must be >= 1. Pass 0 to keep nothing (dangerous — use with care).
    dry_run:
        If True, files are identified but not deleted. Useful for testing
        and for previewing what would be removed.

    Returns
    -------
    RetentionResult
        Summary of what was deleted, kept, and any errors encountered.

    Raises
    ------
    ValueError
        If *retention_days* is negative.
    """
    log_dir = Path(log_dir)

    if retention_days < 0:
        raise ValueError(
            f"retention_days must be >= 0, got {retention_days}."
        )

    if not log_dir.exists():
        # Nothing to sweep — not an error
        return RetentionResult(deleted=[], kept=[], errors=[])

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)

    deleted: list[Path] = []
    kept:    list[Path] = []
    errors:  list[tuple[Path, Exception]] = []

    for file in _iter_log_files(log_dir):
        try:
            mtime = _mtime_utc(file)
            if mtime < cutoff:
                if not dry_run:
                    file.unlink()
                deleted.append(file)
                log.debug(
                    "%s %s (modified %s, older than %d days)",
                    "Would delete" if dry_run else "Deleted",
                    file,
                    mtime.strftime("%Y-%m-%d"),
                    retention_days,
                )
            else:
                kept.append(file)
        except Exception as exc:
            errors.append((file, exc))
            log.warning("Could not process log file '%s': %s", file, exc)

    result = RetentionResult(deleted=deleted, kept=kept, errors=errors)

    if deleted or errors:
        log.info(
            "Log retention sweep%s: %s",
            " (dry run)" if dry_run else "",
            result,
        )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_log_files(root: Path):
    """Yield all log files under *root* recursively."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if _is_log_file(path):
                yield path


def _is_log_file(path: Path) -> bool:
    """Return True if *path* looks like a log file we own.

    Matches:
        app.log
        app.2025-03-22.log
        error.log.1               (rotation backup)
        error.2025-03-22.log.3    (rotation backup)
    """
    name = path.name
    # Direct .log extension
    if path.suffix == ".log":
        return True
    # Rotation backups: .log.1, .log.2, etc.
    parts = name.rsplit(".", 2)
    if len(parts) >= 2 and parts[-2] == "log" and parts[-1].isdigit():
        return True
    return False


def _mtime_utc(path: Path) -> datetime:
    """Return the last-modified time of *path* as a UTC-aware datetime."""
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc)