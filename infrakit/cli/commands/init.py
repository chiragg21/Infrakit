"""
infrakit.cli.commands.init
~~~~~~~~~~~~~~~~~~~~~~~~~~
``infrakit init`` command — scaffold a new project from a template.

This is registered directly on the root app (not as a sub-Typer) so that
``ik init <project>`` works without an extra subcommand layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from infrakit.scaffolder import *

# ── helpers ───────────────────────────────────────────────────────────────────

_CONFIG_FORMATS = {"env", "yaml", "json"}
_DEPS_FORMATS   = {"toml", "requirements"}


def _abort(msg: str) -> None:
    typer.echo(typer.style(f"✗  {msg}", fg=typer.colors.RED), err=True)
    raise typer.Exit(1)


def _render_entry(entry: ScaffoldEntry, project_dir: Path) -> None:
    rel      = entry.path.relative_to(project_dir.parent)
    kind_tag = typer.style("dir " if entry.kind == "dir" else "file", fg=typer.colors.BRIGHT_BLACK)

    if entry.status == "created":
        icon  = typer.style("+", fg=typer.colors.GREEN, bold=True)
        label = typer.style(str(rel), fg=typer.colors.GREEN)
    else:
        icon  = typer.style("~", fg=typer.colors.BRIGHT_BLACK)
        label = typer.style(str(rel), fg=typer.colors.BRIGHT_BLACK)

    typer.echo(f"  {icon} {kind_tag}  {label}")


# ── command function (registered on root app in main.py) ──────────────────────

template_map = {"basic": scaffold_basic,
                "ai": scaffold_ai,
                "cli_tool": scaffold_cli_tool,
                "pipeline": scaffold_pipeline,
                "backend": scaffold_backend}

def cmd_init(
    project: str = typer.Argument(..., help="Project folder name."),
    template: str = typer.Option("basic", "--template", "-t", help="Template to use."),
    include_llm: bool = typer.Option(False, "--include-llm", "-l", help="Include LLM client."),
    version: str = typer.Option("0.1.0", "--version", "-v", help="Starting version."),
    description: str = typer.Option("", "--description", "-d", help="Short project description."),
    author: str = typer.Option("", "--author", "-a", help='Author e.g. "Jane Doe <jane@example.com>".'),
    config_fmt: str = typer.Option("env", "--config", "-c", help="Config format: env (default) | yaml | json."),
    deps: str = typer.Option("toml", "--deps", help="Dependency file: toml (default) | requirements."),
    target_dir: Optional[Path] = typer.Option(None, "--dir", help="Parent directory (default: cwd)."),
) -> None:
    """
    Scaffold a new project. Safe to re-run — existing files are never overwritten.

    \b
    Examples
    --------
      ik init my-project
      ik init my-project --version 0.2.0 --author "Jane Doe" --description "My app"
      ik init my-project --config yaml --deps requirements
      ik init my-project --dir ~/projects
    """
    if config_fmt not in _CONFIG_FORMATS:
        _abort(f"Unknown config format '{config_fmt}'. Choose from: {', '.join(sorted(_CONFIG_FORMATS))}")

    if deps not in _DEPS_FORMATS:
        _abort(f"Unknown deps format '{deps}'. Choose from: {', '.join(sorted(_DEPS_FORMATS))}")

    base        = target_dir.resolve() if target_dir else Path.cwd()
    project_dir = base / project

    typer.echo()
    typer.echo(typer.style(f"Scaffolding project: {project}", bold=True))
    typer.echo(typer.style(f"Location: {project_dir}", fg=typer.colors.BRIGHT_BLACK))
    typer.echo()

    try:
        scaffolder = template_map.get(template)
        if scaffolder is None:
            _abort(f"Unknown template '{template}'. Choose from: {', '.join(sorted(template_map.keys()))}")
        result = scaffolder(
            project_dir,
            version=version,
            description=description,
            author=author,
            config_fmt=config_fmt,
            deps=deps,
            include_llm = include_llm,
        )
    except Exception as exc:  # noqa: BLE001
        _abort(f"Scaffolding failed: {exc}")
        return

    for entry in result.entries:
        _render_entry(entry, project_dir)

    typer.echo()

    n_created = len(result.created)
    n_skipped = len(result.skipped)

    if n_created == 0:
        typer.echo(typer.style("  Nothing new — project already up to date.", fg=typer.colors.BRIGHT_BLACK))
    else:
        typer.echo(
            typer.style(f"  ✓  {n_created} item(s) created", fg=typer.colors.GREEN)
            + (typer.style(f", {n_skipped} skipped", fg=typer.colors.BRIGHT_BLACK) if n_skipped else "")
        )

    typer.echo()

    if n_created > 0:
        typer.echo(typer.style("  Next steps:", fg=typer.colors.BRIGHT_BLACK))
        typer.echo(f"    {typer.style(f'cd {project}', fg=typer.colors.CYAN)}")
        if deps == "toml":
            typer.echo(f"    {typer.style('uv pip install -e .', fg=typer.colors.CYAN)}")
        else:
            typer.echo(f"    {typer.style('pip install -r requirements.txt', fg=typer.colors.CYAN)}")
        typer.echo()