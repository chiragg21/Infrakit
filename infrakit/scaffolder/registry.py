"""
infrakit.scaffolder.templates.registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Central registry mapping template names to their scaffold functions.

Usage (programmatic)
---------------------
    from infrakit.scaffolder.templates.registry import get_template, list_templates

    fn   = get_template("ai")
    fn(Path("my_project"), version="0.2.0", include_notebooks=True)

Usage (CLI)
-----------
    ik init my_project --template backend
    ik init my_project --template pipeline --include-llm
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    description: str
    fn: Callable
    extra_flags: list[str]   # optional flags supported by this template


def _load_registry() -> dict[str, TemplateInfo]:
    # Imports are deferred so that only the SDK(s) required by the chosen
    # template need to be installed (e.g. openai is not needed for cli_tool).
    from infrakit.scaffolder.generator import scaffold_basic
    from infrakit.scaffolder.templates.ai       import scaffold_ai
    from infrakit.scaffolder.templates.backend  import scaffold_backend
    from infrakit.scaffolder.templates.cli_tool import scaffold_cli_tool
    from infrakit.scaffolder.templates.pipeline import scaffold_pipeline

    entries = [
        TemplateInfo(
            name="basic",
            description="Minimal project — src/, utils/, tests/, logger.",
            fn=scaffold_basic,
            extra_flags=[],
        ),
        TemplateInfo(
            name="ai",
            description=(
                "AI / ML project — pipelines, data dirs, notebooks, "
                "utils/llm.py, utils/logger.py, prompts/."
            ),
            fn=scaffold_ai,
            extra_flags=["--include-notebooks"],
        ),
        TemplateInfo(
            name="backend",
            description=(
                "FastAPI service — app/, routes/, services/, middleware/, "
                "utils/llm.py, Dockerfile, docker-compose."
            ),
            fn=scaffold_backend,
            extra_flags=["--include-llm / --no-include-llm"],
        ),
        TemplateInfo(
            name="cli-tool",
            description=(
                "Distributable Typer CLI — src/<pkg>/cli/, commands/, "
                "entry point wired via pyproject.toml."
            ),
            fn=scaffold_cli_tool,
            extra_flags=["--include-llm / --no-include-llm"],
        ),
        TemplateInfo(
            name="pipeline",
            description=(
                "Data pipeline / ETL — extract, transform, enrich, load stages, "
                "schemas/, data dirs."
            ),
            fn=scaffold_pipeline,
            extra_flags=["--include-llm / --no-include-llm"],
        ),
    ]
    return {e.name: e for e in entries}


# module-level singleton
_REGISTRY: dict[str, TemplateInfo] | None = None


def _registry() -> dict[str, TemplateInfo]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_registry()
    return _REGISTRY


def list_templates() -> list[TemplateInfo]:
    """Return all registered templates in definition order."""
    return list(_registry().values())


def get_template(name: str) -> Callable:
    """
    Return the scaffold function for *name*.

    Raises
    ------
    ValueError
        If *name* is not a known template.
    """
    reg = _registry()
    if name not in reg:
        available = ", ".join(f"'{k}'" for k in reg)
        raise ValueError(
            f"Unknown template '{name}'. Available: {available}"
        )
    return reg[name].fn