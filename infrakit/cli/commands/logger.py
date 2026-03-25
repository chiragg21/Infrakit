"""
infrakit.cli.commands.logger
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``infrakit logger`` subcommand group.

Commands
--------
    infrakit logger check               — show active INFRAKIT_LOG_* env vars
    infrakit logger clean <log_dir>     — manually run a retention sweep
"""

from __future__ import annotations

from pathlib import Path

import typer

logger_app = typer.Typer(
    name="logger",
    help="Inspect and maintain infrakit logger state.",
    no_args_is_help=True,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _abort(msg: str) -> None:
    typer.echo(typer.style(f"✗  {msg}", fg=typer.colors.RED), err=True)
    raise typer.Exit(1)


def _ok(msg: str) -> None:
    typer.echo(typer.style(f"✓  {msg}", fg=typer.colors.GREEN))


# ── infrakit logger check ─────────────────────────────────────────────────────

_ENV_VARS = [
    ("INFRAKIT_LOG_DIR",       "log_dir",        "logs"),
    ("INFRAKIT_LOG_STRATEGY",  "strategy",       "date"),
    ("INFRAKIT_LOG_STREAM",    "stream",         "stdout"),
    ("INFRAKIT_LOG_FORMAT",    "format",         "human"),
    ("INFRAKIT_LOG_LEVEL",     "level",          "DEBUG"),
    ("INFRAKIT_LOG_SESSION",   "session",        "<timestamped>"),
    ("INFRAKIT_LOG_RETENTION", "retention_days", "<none>"),
    ("INFRAKIT_LOG_DRY_RUN",   "dry_run",        "false"),
]


@logger_app.command("check")
def cmd_check() -> None:
    """
    Show the current INFRAKIT_LOG_* environment variables.

    Useful for verifying your env before running an application —
    whatever is shown here is exactly what setup() will pick up.

    \b
    Examples
    --------
      ik logger check
    """
    import os

    typer.echo(typer.style("infrakit logger — env configuration", bold=True))
    typer.echo()

    any_set = False
    for env_key, label, default in _ENV_VARS:
        raw = os.environ.get(env_key)
        if raw is not None:
            any_set = True
            val_str = typer.style(raw, fg=typer.colors.GREEN)
            src     = typer.style("(env)", fg=typer.colors.BRIGHT_BLACK)
        else:
            val_str = typer.style(default, fg=typer.colors.BRIGHT_BLACK)
            src     = typer.style("(default)", fg=typer.colors.BRIGHT_BLACK)

        label_str = typer.style(f"{label:<20}", fg=typer.colors.CYAN)
        typer.echo(f"  {label_str} {val_str}  {src}")

    typer.echo()
    if any_set:
        _ok("Some INFRAKIT_LOG_* vars are set — setup() will use them automatically.")
    else:
        typer.echo(typer.style(
            "   No INFRAKIT_LOG_* vars set — all defaults will apply.",
            fg=typer.colors.BRIGHT_BLACK,
        ))


# ── infrakit logger clean ─────────────────────────────────────────────────────

@logger_app.command("clean")
def cmd_clean(
    log_dir: Path = typer.Argument(..., help="Log directory to sweep."),
    days: int = typer.Option(..., "--days", "-d", help="Delete files older than this many days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted without removing anything."),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm", help="Prompt before deleting (default: on)."),
) -> None:
    """
    Run a retention sweep on a log directory.

    Always does a dry-run preview first, then (if --no-confirm is not set)
    prompts before actually deleting.

    \b
    Examples
    --------
      ik logger clean ./logs --days 7
      ik logger clean /var/log/myapp --days 30 --dry-run
      ik logger clean ./logs --days 3 --no-confirm
    """
    if not log_dir.exists():
        _abort(f"Directory not found: {log_dir}")

    if days < 1:
        _abort("--days must be at least 1.")

    from infrakit.core.logger.retention import sweep

    # ── dry-run pass: find candidates without deleting ────────────────────────
    try:
        preview = sweep(log_dir, retention_days=days, dry_run=True)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Retention scan failed: {exc}")
        return

    if not preview.deleted:
        _ok(f"No log files older than {days} day(s) found in {log_dir}.")
        return

    typer.echo(typer.style(
        f"  Found {len(preview.deleted)} file(s) older than {days} day(s):",
        bold=True,
    ))
    for p in preview.deleted:
        typer.echo(f"   {typer.style(str(p), fg=typer.colors.YELLOW)}")
    typer.echo()

    # ── dry-run mode: stop here ───────────────────────────────────────────────
    if dry_run:
        typer.echo(typer.style("   Dry-run — nothing deleted.", fg=typer.colors.BRIGHT_BLACK))
        return

    # ── confirm prompt ────────────────────────────────────────────────────────
    if confirm:
        typer.confirm(f"  Delete {len(preview.deleted)} file(s)?", abort=True)

    # ── live pass: actually delete ────────────────────────────────────────────
    try:
        result = sweep(log_dir, retention_days=days, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Deletion failed: {exc}")
        return

    _ok(f"Deleted {len(result.deleted)} file(s).")

    if result.errors:
        for path, exc in result.errors:
            typer.echo(typer.style(f"⚠  Error on {path}: {exc}", fg=typer.colors.YELLOW), err=True)