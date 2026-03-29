"""
infrakit.scaffolder.templates.cli_tool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Scaffold a distributable Typer CLI tool.

Layout
------
<project>/
├── src/
│   └── <project>/          # importable package (same name as project)
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py     # root Typer app + entry point
│       │   └── commands/
│       │       ├── __init__.py
│       │       └── run.py  # starter "run" command group
│       └── core.py         # library logic (CLI-agnostic)
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   └── llm.py              # optional — for AI-powered CLI tools
├── tests/
│   ├── __init__.py
│   └── test_cli.py
├── logs/
├── pyproject.toml / requirements.txt   # entry_points wired up
├── config.{env|yaml|json}
├── README.md
└── .gitignore
"""

from __future__ import annotations

from pathlib import Path

from infrakit.scaffolder.generator import (
    ScaffoldResult,
    _mkdir,
    _write,
    _config_content,
    _gitignore,
    _logger_util,
    _src_init,
    _tests_init,
)
from infrakit.scaffolder.ai import _llm_util


# ── template content ──────────────────────────────────────────────────────────


def _cli_main(project_name: str, version: str) -> str:
    cmd = project_name.replace("_", "-")
    return f'''\
"""
{project_name}.cli.main
{"~" * (len(project_name) + 10)}
Root Typer application.

Entry point: ``{cmd}`` (wired via pyproject.toml).
"""

import typer

from {project_name}.cli.commands import run as run_cmd
from utils.logger import get_logger

log = get_logger(__name__)

app = typer.Typer(
    name="{cmd}",
    help="{project_name.replace("_", " ").title()} CLI.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

# ── register command groups ───────────────────────────────────────────────────
app.add_typer(run_cmd.app, name="run")


def version_callback(value: bool) -> None:
    if value:
        from {project_name} import __version__
        typer.echo(f"{cmd} {{__version__}}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


def cli() -> None:
    """Entry point called by the ``{cmd}`` script."""
    app()


if __name__ == "__main__":
    cli()
'''


def _cli_commands_init() -> str:
    return '"""CLI command modules."""\n'


def _cli_run_command(project_name: str) -> str:
    return f'''\
"""
{project_name}.cli.commands.run
{"~" * (len(project_name) + 20)}
Example "run" command group.  Replace with your own commands.
"""

import typer
from typing_extensions import Annotated

from {project_name}.core import do_something
from utils.logger import get_logger

log = get_logger(__name__)

app = typer.Typer(
    name="run",
    help="Run project operations.",
    no_args_is_help=True,
)


@app.command("hello")
def hello(
    name: Annotated[str, typer.Argument(help="Name to greet.")] = "World",
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Say hello."""
    result = do_something(name)
    if verbose:
        log.info("hello: %s -> %s", name, result)
    typer.echo(result)
'''


def _core(project_name: str) -> str:
    return f'''\
"""
{project_name}.core
{"~" * (len(project_name) + 6)}
Library logic — no CLI dependencies here.

Keeping business logic separate from CLI code means it can be imported,
tested, and reused without invoking Typer.
"""


def do_something(name: str) -> str:
    """Placeholder — replace with real logic."""
    return f"Hello, {{name}}!"
'''


def _test_cli(project_name: str) -> str:
    cmd = project_name.replace("_", "-")
    return f'''\
"""tests.test_cli — basic CLI smoke tests."""

from typer.testing import CliRunner

from {project_name}.cli.main import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_hello_default():
    result = runner.invoke(app, ["run", "hello"])
    assert result.exit_code == 0
    assert "Hello" in result.output


def test_hello_name():
    result = runner.invoke(app, ["run", "hello", "Alice"])
    assert result.exit_code == 0
    assert "Alice" in result.output
'''


def _cli_pyproject(
    project_name: str, version: str, description: str, author: str, include_llm: bool
) -> str:
    author_line = f'    "{author}",' if author else '    # "Your Name <you@example.com>",'
    cmd         = project_name.replace("_", "-")
    llm_deps    = """\
    "openai",
    "google-generativeai",
    "tqdm",
""" if include_llm else ""
    return f"""\
[project]
name        = "{project_name}"
version     = "{version}"
description = "{description}"
readme      = "README.md"
requires-python = ">=3.10"
authors = [
{author_line}
]

dependencies = [
    "infrakit",
    "typer[all]",
    "pydantic>=2.0",
{llm_deps}]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
]

[project.scripts]
{cmd} = "{project_name}.cli.main:cli"

[tool.setuptools.packages.find]
where = ["src"]
"""


def _cli_readme(project_name: str, description: str, include_llm: bool) -> str:
    title     = project_name.replace("-", " ").replace("_", " ").title()
    desc_line = f"\n{description}\n" if description else ""
    cmd       = project_name.replace("_", "-")
    llm_note  = (
        "\nThis tool includes `utils/llm.py` — set `OPENAI_API_KEY` or "
        "`GEMINI_API_KEY` in your environment to use LLM features.\n"
    ) if include_llm else ""
    return f"""\
# {title}
{desc_line}{llm_note}
## Installation

```bash
pip install -e .
```

## Usage

```bash
{cmd} --help
{cmd} --version
{cmd} run hello
{cmd} run hello Alice --verbose
```

## Structure

| Path | Purpose |
|---|---|
| `src/{project_name}/cli/main.py` | Root Typer app + entry point |
| `src/{project_name}/cli/commands/` | One file per command group |
| `src/{project_name}/core.py` | Business logic (no CLI deps) |
| `utils/logger.py` | Logger singleton |
{"| `utils/llm.py` | LLM client singleton |" if include_llm else ""}

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Adding a new command group

1. Create `src/{project_name}/cli/commands/mygroup.py` with a `app = typer.Typer(...)`.
2. Register it in `main.py`: `app.add_typer(mygroup.app, name="mygroup")`.
"""


def _cli_gitignore() -> str:
    return _gitignore() + """\
# Keys
.env
keys.json
"""


# ── public API ────────────────────────────────────────────────────────────────


def scaffold_cli_tool(
    project_dir: Path,
    *,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    config_fmt: str = "env",
    deps: str = "toml",
    include_llm: bool = False,
) -> ScaffoldResult:
    """
    Scaffold a distributable Typer CLI tool under ``project_dir``.

    Parameters
    ----------
    project_dir:
        Root directory for the project.
    version:
        Starting version string.
    description:
        Short project description.
    author:
        Author string.
    config_fmt:
        Config file format — ``"env"``, ``"yaml"``, or ``"json"``.
    deps:
        ``"toml"`` or ``"requirements"``.
    include_llm:
        Whether to include ``utils/llm.py`` for AI-powered CLI commands.
        Defaults to False for pure CLI tools.
    """
    result       = ScaffoldResult(project_dir=project_dir)
    project_name = project_dir.name

    pkg_dir = project_dir / "src" / project_name

    # ── directories ───────────────────────────────────────────────────────────
    _mkdir(result, project_dir)
    _mkdir(result, pkg_dir)
    _mkdir(result, pkg_dir / "cli")
    _mkdir(result, pkg_dir / "cli" / "commands")
    _mkdir(result, project_dir / "utils")
    _mkdir(result, project_dir / "tests")
    _mkdir(result, project_dir / "logs")

    # ── package ───────────────────────────────────────────────────────────────
    _write(result, pkg_dir / "__init__.py",              _src_init(version))
    _write(result, pkg_dir / "core.py",                  _core(project_name))

    # ── cli ───────────────────────────────────────────────────────────────────
    _write(result, pkg_dir / "cli" / "__init__.py",      '"""CLI package."""\n')
    _write(result, pkg_dir / "cli" / "main.py",          _cli_main(project_name, version))
    _write(result, pkg_dir / "cli" / "commands" / "__init__.py",
           _cli_commands_init())
    _write(result, pkg_dir / "cli" / "commands" / "run.py",
           _cli_run_command(project_name))

    # ── utils ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "utils" / "__init__.py", '"""Shared utilities."""\n')
    _write(result, project_dir / "utils" / "logger.py",   _logger_util())
    if include_llm:
        _write(result, project_dir / "utils" / "llm.py",  _llm_util(project_name))

    # ── tests ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "tests" / "__init__.py",  _tests_init())
    _write(result, project_dir / "tests" / "test_cli.py",  _test_cli(project_name))

    # ── config ────────────────────────────────────────────────────────────────
    cfg_name, cfg_content = _config_content(config_fmt)
    _write(result, project_dir / cfg_name, cfg_content)

    # ── dependency file ───────────────────────────────────────────────────────
    if deps == "requirements":
        from infrakit.scaffolder.generator import _requirements_txt
        _write(result, project_dir / "requirements.txt",
               _requirements_txt(project_name))
    else:
        _write(result, project_dir / "pyproject.toml",
               _cli_pyproject(project_name, version, description, author, include_llm))

    # ── repo files ────────────────────────────────────────────────────────────
    _write(result, project_dir / "README.md",
           _cli_readme(project_name, description, include_llm))
    _write(result, project_dir / ".gitignore", _cli_gitignore())

    return result