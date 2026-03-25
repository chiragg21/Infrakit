"""
infrakit.scaffolder.generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Core scaffolding logic for the ``basic`` project template.

Idempotent — any file or directory that already exists is left untouched.
Every action (created / skipped) is reported back to the caller via
``ScaffoldResult`` so the CLI can render it however it likes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ── types ─────────────────────────────────────────────────────────────────────

Status = Literal["created", "skipped"]


@dataclass
class ScaffoldEntry:
    path: Path
    status: Status
    kind: Literal["file", "dir"]


@dataclass
class ScaffoldResult:
    project_dir: Path
    entries: list[ScaffoldEntry] = field(default_factory=list)

    # convenience views
    @property
    def created(self) -> list[ScaffoldEntry]:
        return [e for e in self.entries if e.status == "created"]

    @property
    def skipped(self) -> list[ScaffoldEntry]:
        return [e for e in self.entries if e.status == "skipped"]


# ── helpers ───────────────────────────────────────────────────────────────────


def _write(result: ScaffoldResult, path: Path, content: str) -> None:
    """Write a file only if it doesn't exist yet; record the outcome."""
    if path.exists():
        result.entries.append(ScaffoldEntry(path=path, status="skipped", kind="file"))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.entries.append(ScaffoldEntry(path=path, status="created", kind="file"))


def _mkdir(result: ScaffoldResult, path: Path) -> None:
    """Create a directory only if it doesn't exist yet; record the outcome."""
    if path.exists():
        result.entries.append(ScaffoldEntry(path=path, status="skipped", kind="dir"))
        return
    path.mkdir(parents=True, exist_ok=True)
    result.entries.append(ScaffoldEntry(path=path, status="created", kind="dir"))


# ── template content ──────────────────────────────────────────────────────────

def _pyproject_toml(
    project_name: str,
    version: str,
    description: str,
    author: str,
) -> str:
    author_line = f'    "{author}",' if author else '    # "Your Name <you@example.com>",'
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
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
]
"""


def _requirements_txt(project_name: str) -> str:
    return f"""\
# requirements.txt — {project_name}
# Add your dependencies below.
infrakit
"""


def _env_config() -> str:
    return """\
# Application configuration
# Copy this file to .env.local and fill in the values.
APP_ENV=development
APP_DEBUG=false
APP_SECRET=YOUR_VALUE_HERE
"""


def _yaml_config() -> str:
    return """\
# Application configuration
app:
  env: development
  debug: false
  secret: YOUR_VALUE_HERE
"""


def _json_config() -> str:
    return """\
{
  "app": {
    "env": "development",
    "debug": false,
    "secret": "YOUR_VALUE_HERE"
  }
}
"""


def _config_content(fmt: str) -> tuple[str, str]:
    """Return (filename, content) for the chosen config format."""
    if fmt == "yaml":
        return "config.yaml", _yaml_config()
    if fmt == "json":
        return "config.json", _json_config()
    return ".env", _env_config()  # default


def _logger_util() -> str:
    return """\
\"\"\"
utils.logger
~~~~~~~~~~~~
Thin wrapper that boots the infrakit logger once and exports ``get_logger``.

Usage
-----
    from utils.logger import get_logger

    log = get_logger(__name__)
    log.info("hello")
\"\"\"

import os
from infrakit.core.logger import setup, get_logger  # re-export get_logger

_booted = False


def _boot() -> None:
    global _booted
    if _booted:
        return
    setup(
        log_dir=os.getenv("LOG_DIR", "logs"),
        strategy=os.getenv("LOG_STRATEGY", "date"),
        stream=os.getenv("LOG_STREAM", "stdout"),
        fmt=os.getenv("LOG_FORMAT", "human"),
        level=os.getenv("LOG_LEVEL", "DEBUG"),
    )
    _booted = True


_boot()

__all__ = ["get_logger"]
"""


def _readme(project_name: str, description: str) -> str:
    title    = project_name.replace("-", " ").replace("_", " ").title()
    desc_line = f"\n{description}\n" if description else ""
    return f"""\
# {title}
{desc_line}
## Setup

```bash
pip install -e .
```

## Usage

```python
from utils.logger import get_logger

log = get_logger(__name__)
log.info("hello")
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
"""


def _gitignore() -> str:
    return """\
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.eggs/

# Virtual envs
.venv/
venv/
env/

# Logs
logs/
*.log

# Env files
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp

# Testing
.pytest_cache/
.coverage
htmlcov/

# uv
uv.lock
"""


def _src_init(version: str) -> str:
    return f'__version__ = "{version}"\n'


def _tests_init() -> str:
    return '"""Test suite."""\n'


# ── public API ────────────────────────────────────────────────────────────────

def scaffold_basic(
    project_dir: Path,
    *,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    config_fmt: str = "env",
    deps: str = "toml",
) -> ScaffoldResult:
    """
    Scaffold a basic project layout under ``project_dir``.

    Parameters
    ----------
    project_dir:
        Root directory for the project (will be created if absent).
    version:
        Starting version string, e.g. ``"0.1.0"``.
    description:
        Short project description used in pyproject.toml / README.
    author:
        Author string, e.g. ``"Jane Doe <jane@example.com>"``.
    config_fmt:
        Config file format — ``"env"`` (default), ``"yaml"``, or ``"json"``.
    deps:
        Dependency file style — ``"toml"`` (default) or ``"requirements"``.
    """
    result       = ScaffoldResult(project_dir=project_dir)
    project_name = project_dir.name

    # ── directories ───────────────────────────────────────────────────────────
    _mkdir(result, project_dir)
    _mkdir(result, project_dir / "src")
    _mkdir(result, project_dir / "utils")
    _mkdir(result, project_dir / "tests")
    _mkdir(result, project_dir / "logs")

    # ── src ───────────────────────────────────────────────────────────────────
    _write(result, project_dir / "src" / "__init__.py", _src_init(version))

    # ── utils ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "utils" / "__init__.py", '"""Shared utilities."""\n')
    _write(result, project_dir / "utils" / "logger.py", _logger_util())

    # ── tests ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "tests" / "__init__.py", _tests_init())

    # ── config file ───────────────────────────────────────────────────────────
    cfg_name, cfg_content = _config_content(config_fmt)
    _write(result, project_dir / cfg_name, cfg_content)

    # ── dependency file ───────────────────────────────────────────────────────
    if deps == "requirements":
        _write(result, project_dir / "requirements.txt", _requirements_txt(project_name))
    else:
        _write(
            result,
            project_dir / "pyproject.toml",
            _pyproject_toml(project_name, version, description, author),
        )

    # ── repo files ────────────────────────────────────────────────────────────
    _write(result, project_dir / "README.md", _readme(project_name, description))
    _write(result, project_dir / ".gitignore", _gitignore())

    return result