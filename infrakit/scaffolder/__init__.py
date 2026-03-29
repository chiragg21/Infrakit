"""
infrakit.scaffolder.templates
------------------------------
Project template scaffolders.

Quick reference
---------------
    from infrakit.scaffolder.templates.registry import get_template, list_templates
    from infrakit.scaffolder.templates.ai       import scaffold_ai
    from infrakit.scaffolder.templates.backend  import scaffold_backend
    from infrakit.scaffolder.templates.cli_tool import scaffold_cli_tool
    from infrakit.scaffolder.templates.pipeline import scaffold_pipeline
"""
from infrakit.scaffolder.generator import scaffold_basic, ScaffoldEntry, ScaffoldResult
from infrakit.scaffolder.ai       import scaffold_ai
from infrakit.scaffolder.backend  import scaffold_backend
from infrakit.scaffolder.cli_tool import scaffold_cli_tool
from infrakit.scaffolder.pipeline import scaffold_pipeline
from infrakit.scaffolder.registry import get_template, list_templates

__all__ = [
    'scaffold_basic',
    'ScaffoldEntry',
    'ScaffoldResult',
    "scaffold_ai",
    "scaffold_backend",
    "scaffold_cli_tool",
    "scaffold_pipeline",
    "get_template",
    "list_templates",
]