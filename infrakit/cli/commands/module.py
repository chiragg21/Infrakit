"""
infrakit.cli.commands.module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``infrakit module`` subcommand group.

Commands
--------
    infrakit module create <path> [--no-init] [--no-init-parents]
    infrakit module delete <path> [--no-confirm]
    infrakit module tree   [root]  [--show-ignored]
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import Optional

import typer

module_app = typer.Typer(
    name="module",
    help="Create, delete, or inspect module directories.",
    no_args_is_help=True,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _abort(msg: str) -> None:
    typer.echo(typer.style(f"✗  {msg}", fg=typer.colors.RED), err=True)
    raise typer.Exit(1)


def _created(rel: Path) -> None:
    typer.echo(f"  {typer.style('+', fg=typer.colors.GREEN, bold=True)}  {rel}")


def _skipped(rel: Path, reason: str = "already exists") -> None:
    typer.echo(
        f"  {typer.style('~', fg=typer.colors.BRIGHT_BLACK)}  "
        f"{typer.style(str(rel), fg=typer.colors.BRIGHT_BLACK)}"
        f"  {typer.style(f'({reason})', fg=typer.colors.BRIGHT_BLACK)}"
    )


def _write_init(path: Path, cwd: Path) -> None:
    rel = path.relative_to(cwd)
    if path.exists():
        _skipped(rel)
        return
    path.write_text('"""{}"""\n'.format(path.parent.name), encoding="utf-8")
    _created(rel)


def _make_dir(path: Path, cwd: Path) -> None:
    rel = path.relative_to(cwd)
    if path.exists():
        _skipped(rel)
        return
    path.mkdir(parents=True, exist_ok=True)
    _created(rel)


# ── gitignore parser ──────────────────────────────────────────────────────────

def _load_gitignore_patterns(root: Path) -> list[str]:
    """
    Read .gitignore from root and return a list of raw patterns.
    Always includes .git itself regardless of .gitignore contents.
    """
    patterns: list[str] = [".git"]
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return patterns
    for line in gitignore.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """
    Return True if ``path`` matches any gitignore pattern.

    Handles:
    - globstar prefix  **/<name>/  — match bare name at any depth
    - bare patterns    __pycache__ — match any path component
    - anchored patterns src/*.py   — match against full relative path
    - trailing slashes stripped    (directory-only markers)
    """
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.name

    rel_parts = Path(rel).parts

    for pattern in patterns:
        # ── globstar: **/<name> or **/<name>/ → bare name at any depth ───────
        if pattern.startswith("**/"):
            bare = pattern[3:].rstrip("/")
            if any(fnmatch.fnmatch(part, bare) for part in rel_parts):
                return True
            continue

        p = pattern.rstrip("/")

        # ── bare name (no slash) → match against every path component ────────
        if "/" not in p:
            if any(fnmatch.fnmatch(part, p) for part in rel_parts):
                return True
        else:
            # ── anchored pattern (contains slash) → match full relative path ─
            if fnmatch.fnmatch(rel, p):
                return True

    return False


# ── tree renderer ─────────────────────────────────────────────────────────────

_PIPE   = "│   "
_TEE    = "├── "
_LAST   = "└── "
_BLANK  = "    "


def _render_tree(
    path: Path,
    root: Path,
    patterns: list[str],
    show_ignored: bool,
    prefix: str = "",
) -> tuple[int, int]:
    """
    Recursively render the tree under ``path``.
    Returns (dir_count, file_count).
    """
    dirs  = 0
    files = 0

    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return dirs, files

    # filter ignored unless show_ignored
    if not show_ignored:
        entries = [e for e in entries if not _is_ignored(e, root, patterns)]

    for i, entry in enumerate(entries):
        is_last   = i == len(entries) - 1
        connector = _LAST if is_last else _TEE
        extension = _BLANK if is_last else _PIPE
        ignored   = _is_ignored(entry, root, patterns)

        if entry.is_dir():
            dirs += 1
            label = typer.style(entry.name + "/", fg=typer.colors.CYAN, bold=True)
            dim   = typer.style(" (ignored)", fg=typer.colors.BRIGHT_BLACK) if ignored else ""
            typer.echo(f"{prefix}{connector}{label}{dim}")
            d, f = _render_tree(entry, root, patterns, show_ignored, prefix + extension)
            dirs  += d
            files += f
        else:
            files += 1
            if ignored:
                label = typer.style(entry.name, fg=typer.colors.BRIGHT_BLACK)
                dim   = typer.style(" (ignored)", fg=typer.colors.BRIGHT_BLACK)
            else:
                label = entry.name
                dim   = ""
            typer.echo(f"{prefix}{connector}{label}{dim}")

    return dirs, files


# ── ik module create ──────────────────────────────────────────────────────────

@module_app.command("create")
def cmd_create(
    module_path: str = typer.Argument(
        ...,
        help="Module path, supports nesting e.g. core/models or just utils.",
    ),
    init: bool = typer.Option(
        True, "--init/--no-init",
        help="Add __init__.py to the final module directory (default: on).",
    ),
    init_parents: bool = typer.Option(
        True, "--init-parents/--no-init-parents",
        help="Add __init__.py to intermediate parent directories (default: on).",
    ),
) -> None:
    """
    Create a module directory with optional __init__.py files.

    Supports nested paths — intermediate directories are created automatically.
    Any directory or file that already exists is left untouched.

    \b
    Examples
    --------
      ik module create utils
      ik module create core/models
      ik module create core/models --no-init-parents   # skip __init__.py in core/
      ik module create core/models --no-init           # folder only, no __init__.py anywhere
    """
    cwd   = Path.cwd()
    parts = Path(module_path).parts

    if not parts:
        _abort("Module path cannot be empty.")

    typer.echo()

    for i, _ in enumerate(parts):
        current = cwd / Path(*parts[: i + 1])
        is_leaf = i == len(parts) - 1

        _make_dir(current, cwd)

        if is_leaf:
            if init:
                _write_init(current / "__init__.py", cwd)
        else:
            if init_parents:
                _write_init(current / "__init__.py", cwd)

    typer.echo()
    typer.echo(typer.style(f"  ✓  module '{module_path}' ready.", fg=typer.colors.GREEN))
    typer.echo()


# ── ik module delete ──────────────────────────────────────────────────────────

@module_app.command("delete")
def cmd_delete(
    target: Path = typer.Argument(..., help="Module folder to delete."),
    confirm: bool = typer.Option(
        True, "--confirm/--no-confirm",
        help="Prompt before deleting (default: on).",
    ),
) -> None:
    """
    Delete a module directory and everything inside it.

    \b
    Examples
    --------
      ik module delete core/models
      ik module delete core/models --no-confirm
    """
    cwd  = Path.cwd()
    path = (cwd / target).resolve()

    if not path.exists():
        _abort(f"Path not found: {target}")

    if not path.is_dir():
        _abort(f"Not a directory: {target}")

    try:
        path.relative_to(cwd)
    except ValueError:
        _abort("Cannot delete a path outside the current working directory.")

    if path == cwd:
        _abort("Cannot delete the current working directory.")

    rel        = path.relative_to(cwd)
    file_count = sum(1 for f in path.rglob("*") if f.is_file())

    typer.echo()
    typer.echo(
        typer.style("  About to delete: ", fg=typer.colors.BRIGHT_BLACK)
        + typer.style(str(rel), fg=typer.colors.YELLOW, bold=True)
    )
    typer.echo(typer.style(f"  Contains {file_count} file(s).", fg=typer.colors.BRIGHT_BLACK))
    typer.echo()

    if confirm:
        typer.confirm("  Confirm delete?", abort=True)

    try:
        shutil.rmtree(path)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Delete failed: {exc}")

    typer.echo()
    typer.echo(typer.style(f"  ✓  Deleted {rel}", fg=typer.colors.GREEN))
    typer.echo()


# ── ik module tree ────────────────────────────────────────────────────────────

@module_app.command("tree")
def cmd_tree(
    root: Optional[Path] = typer.Argument(
        None,
        help="Root directory to print. Defaults to cwd.",
    ),
    show_ignored: bool = typer.Option(
        False, "--show-ignored",
        help="Include files and folders matched by .gitignore.",
    ),
) -> None:
    """
    Print the directory tree of a project.

    Reads .gitignore from the root directory and hides matched
    entries by default. Pass --show-ignored to reveal them (dimmed).

    \b
    Examples
    --------
      ik module tree
      ik module tree ./my-project
      ik module tree --show-ignored
    """
    target = (root or Path.cwd()).resolve()

    if not target.exists():
        _abort(f"Path not found: {target}")
    if not target.is_dir():
        _abort(f"Not a directory: {target}")

    patterns = _load_gitignore_patterns(target)

    typer.echo()
    typer.echo(typer.style(target.name + "/", fg=typer.colors.CYAN, bold=True))

    dirs, files = _render_tree(target, target, patterns, show_ignored)

    typer.echo()
    summary = typer.style(f"  {dirs} director{'ies' if dirs != 1 else 'y'}, {files} file{'s' if files != 1 else ''}", fg=typer.colors.BRIGHT_BLACK)
    if not show_ignored:
        summary += typer.style("  (.gitignore applied — use --show-ignored to reveal)", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(summary)
    typer.echo()