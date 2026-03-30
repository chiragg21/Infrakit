"""
tests/test_scaffolders.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for infrakit.scaffolder — all five templates.

Run with:  uv run pytest tests/test_scaffolders.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from infrakit.scaffolder.generator import scaffold_basic, ScaffoldResult
from infrakit.scaffolder.ai import scaffold_ai
from infrakit.scaffolder.backend import scaffold_backend
from infrakit.scaffolder.cli_tool import scaffold_cli_tool
from infrakit.scaffolder.pipeline import scaffold_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _files(result: ScaffoldResult) -> set[str]:
    """Relative POSIX paths of every *file* in the result."""
    root = result.project_dir
    return {
        e.path.relative_to(root).as_posix()
        for e in result.entries
        if e.kind == "file"
    }


def _dirs(result: ScaffoldResult) -> set[str]:
    root = result.project_dir
    return {
        e.path.relative_to(root).as_posix()
        for e in result.entries
        if e.kind == "dir"
    }


def _read(project_dir: Path, *parts: str) -> str:
    return (project_dir / Path(*parts)).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# scaffold_basic
# ---------------------------------------------------------------------------

class TestScaffoldBasic:
    def test_creates_expected_dirs(self, tmp_path):
        result = scaffold_basic(tmp_path / "proj")
        dirs = _dirs(result)
        assert "src" in dirs
        assert "utils" in dirs
        assert "tests" in dirs
        assert "logs" in dirs

    def test_creates_expected_files(self, tmp_path):
        result = scaffold_basic(tmp_path / "proj")
        files = _files(result)
        assert "src/__init__.py" in files
        assert "utils/__init__.py" in files
        assert "utils/logger.py" in files
        assert "tests/__init__.py" in files
        assert ".env" in files
        assert "pyproject.toml" in files
        assert "README.md" in files
        assert ".gitignore" in files

    def test_no_llm_by_default(self, tmp_path):
        result = scaffold_basic(tmp_path / "proj")
        assert "utils/llm.py" not in _files(result)

    def test_include_llm(self, tmp_path):
        result = scaffold_basic(tmp_path / "proj", include_llm=True)
        assert "utils/llm.py" in _files(result)
        assert "keys.json" in _files(result)

    def test_env_has_logger_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p)
        env = _read(p, ".env")
        for var in ("LOG_DIR", "LOG_STRATEGY", "LOG_STREAM", "LOG_FORMAT", "LOG_LEVEL"):
            assert var in env, f"{var} missing from .env"

    def test_env_no_llm_vars_by_default(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p)
        env = _read(p, ".env")
        assert "OPENAI_API_KEY" not in env

    def test_env_has_llm_vars_when_requested(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p, include_llm=True)
        env = _read(p, ".env")
        for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_MODE", "LLM_CONCURRENCY"):
            assert var in env, f"{var} missing from .env (include_llm=True)"

    def test_yaml_config_has_logger_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p, config_fmt="yaml")
        cfg = _read(p, "config.yaml")
        for var in ("LOG_DIR", "LOG_STRATEGY", "LOG_LEVEL"):
            assert var in cfg

    def test_json_config_has_logger_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p, config_fmt="json")
        cfg = _read(p, "config.json")
        for var in ("LOG_DIR", "LOG_STRATEGY", "LOG_LEVEL"):
            assert var in cfg

    def test_requirements_deps(self, tmp_path):
        result = scaffold_basic(tmp_path / "proj", deps="requirements")
        assert "requirements.txt" in _files(result)
        assert "pyproject.toml" not in _files(result)

    def test_idempotent(self, tmp_path):
        p = tmp_path / "proj"
        r1 = scaffold_basic(p)
        r2 = scaffold_basic(p)
        created1 = {e.path for e in r1.created}
        skipped2 = {e.path for e in r2.skipped}
        assert created1 == skipped2

    def test_logger_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p)
        src = _read(p, "utils/logger.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src


# ---------------------------------------------------------------------------
# scaffold_ai
# ---------------------------------------------------------------------------

class TestScaffoldAi:
    def test_creates_expected_dirs(self, tmp_path):
        result = scaffold_ai(tmp_path / "proj")
        dirs = _dirs(result)
        for d in ("src", "pipelines", "utils", "prompts", "tests", "logs",
                  "data/raw", "data/processed", "data/outputs"):
            assert d in dirs, f"dir {d!r} missing"

    def test_creates_expected_files(self, tmp_path):
        result = scaffold_ai(tmp_path / "proj")
        files = _files(result)
        for f in (
            "src/__init__.py",
            "pipelines/__init__.py",
            "pipelines/ingest.py",
            "pipelines/preprocess.py",
            "pipelines/predict.py",
            "utils/__init__.py",
            "utils/logger.py",
            "utils/llm.py",
            "prompts/default.txt",
            "tests/__init__.py",
            "keys.json",
            ".env",
            "pyproject.toml",
            "README.md",
            ".gitignore",
        ):
            assert f in files, f"file {f!r} missing"

    def test_notebooks_included_by_default(self, tmp_path):
        result = scaffold_ai(tmp_path / "proj")
        assert "notebooks/01_explore.ipynb" in _files(result)

    def test_notebooks_excluded(self, tmp_path):
        result = scaffold_ai(tmp_path / "proj", include_notebooks=False)
        assert "notebooks/01_explore.ipynb" not in _files(result)

    def test_env_has_logger_and_llm_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        env = _read(p, ".env")
        for var in (
            "LOG_DIR", "LOG_LEVEL",
            "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_MODE", "LLM_CONCURRENCY",
        ):
            assert var in env, f"{var} missing from .env"

    def test_env_no_llm_when_excluded(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p, include_llm=False)
        env = _read(p, ".env")
        assert "OPENAI_API_KEY" not in env
        assert "utils/llm.py" not in _files(scaffold_ai(tmp_path / "proj2", include_llm=False))

    def test_llm_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        src = _read(p, "utils/llm.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_logger_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        src = _read(p, "utils/logger.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_yaml_config_format(self, tmp_path):
        p = tmp_path / "proj"
        result = scaffold_ai(p, config_fmt="yaml")
        assert "config.yaml" in _files(result)
        cfg = _read(p, "config.yaml")
        for var in ("LOG_DIR", "OPENAI_API_KEY", "LLM_MODE"):
            assert var in cfg

    def test_json_config_format(self, tmp_path):
        p = tmp_path / "proj"
        result = scaffold_ai(p, config_fmt="json")
        assert "config.json" in _files(result)
        cfg = _read(p, "config.json")
        for var in ("LOG_DIR", "OPENAI_API_KEY", "LLM_MODE"):
            assert var in cfg

    def test_idempotent(self, tmp_path):
        p = tmp_path / "proj"
        r1 = scaffold_ai(p)
        r2 = scaffold_ai(p)
        assert {e.path for e in r1.created} == {e.path for e in r2.skipped}


# ---------------------------------------------------------------------------
# scaffold_backend
# ---------------------------------------------------------------------------

class TestScaffoldBackend:
    def test_creates_expected_dirs(self, tmp_path):
        result = scaffold_backend(tmp_path / "proj")
        dirs = _dirs(result)
        for d in ("app", "app/routes", "app/models", "app/services",
                  "app/middleware", "utils", "tests", "logs"):
            assert d in dirs, f"dir {d!r} missing"

    def test_creates_expected_files(self, tmp_path):
        result = scaffold_backend(tmp_path / "proj")
        files = _files(result)
        for f in (
            "app/__init__.py",
            "app/main.py",
            "app/config.py",
            "app/dependencies.py",
            "app/routes/health.py",
            "app/models/base.py",
            "app/middleware/logging.py",
            "utils/__init__.py",
            "utils/logger.py",
            "utils/llm.py",
            "tests/__init__.py",
            "tests/test_health.py",
            "Dockerfile",
            "docker-compose.yml",
            ".env",
            "pyproject.toml",
            "README.md",
            ".gitignore",
        ):
            assert f in files, f"file {f!r} missing"

    def test_env_has_backend_and_logger_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        env = _read(p, ".env")
        for var in (
            "APP_NAME", "APP_ENV", "APP_HOST", "APP_PORT",
            "DATABASE_URL",
            "LOG_DIR", "LOG_LEVEL",
        ):
            assert var in env, f"{var} missing from .env"

    def test_env_has_llm_vars_by_default(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        env = _read(p, ".env")
        for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_MODE"):
            assert var in env

    def test_env_no_llm_when_excluded(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p, include_llm=False)
        env = _read(p, ".env")
        assert "OPENAI_API_KEY" not in env

    def test_no_llm_util_when_excluded(self, tmp_path):
        result = scaffold_backend(tmp_path / "proj", include_llm=False)
        assert "utils/llm.py" not in _files(result)
        assert "app/services/llm_service.py" not in _files(result)

    def test_llm_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        src = _read(p, "utils/llm.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_logger_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        src = _read(p, "utils/logger.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_yaml_config_has_backend_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p, config_fmt="yaml")
        cfg = _read(p, "config.yaml")
        for var in ("APP_PORT", "DATABASE_URL", "LOG_DIR"):
            # backend yaml uses nested app section + flat vars
            assert var in cfg or "port" in cfg

    def test_json_config_has_database_url(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p, config_fmt="json")
        cfg = _read(p, "config.json")
        assert "DATABASE_URL" in cfg

    def test_idempotent(self, tmp_path):
        p = tmp_path / "proj"
        r1 = scaffold_backend(p)
        r2 = scaffold_backend(p)
        assert {e.path for e in r1.created} == {e.path for e in r2.skipped}


# ---------------------------------------------------------------------------
# scaffold_cli_tool
# ---------------------------------------------------------------------------

class TestScaffoldCliTool:
    def test_creates_expected_files(self, tmp_path):
        p = tmp_path / "my_tool"
        result = scaffold_cli_tool(p)
        files = _files(result)
        for f in (
            "src/my_tool/__init__.py",
            "src/my_tool/core.py",
            "src/my_tool/cli/__init__.py",
            "src/my_tool/cli/main.py",
            "src/my_tool/cli/commands/__init__.py",
            "src/my_tool/cli/commands/run.py",
            "utils/logger.py",
            "tests/test_cli.py",
            ".env",
            "pyproject.toml",
        ):
            assert f in files, f"file {f!r} missing"

    def test_no_llm_by_default(self, tmp_path):
        result = scaffold_cli_tool(tmp_path / "my_tool")
        assert "utils/llm.py" not in _files(result)

    def test_include_llm(self, tmp_path):
        result = scaffold_cli_tool(tmp_path / "my_tool", include_llm=True)
        assert "utils/llm.py" in _files(result)

    def test_env_has_logger_vars(self, tmp_path):
        p = tmp_path / "my_tool"
        scaffold_cli_tool(p)
        env = _read(p, ".env")
        for var in ("LOG_DIR", "LOG_LEVEL"):
            assert var in env

    def test_env_has_llm_vars_when_requested(self, tmp_path):
        p = tmp_path / "my_tool"
        scaffold_cli_tool(p, include_llm=True)
        env = _read(p, ".env")
        assert "OPENAI_API_KEY" in env

    def test_pyproject_has_entry_point(self, tmp_path):
        p = tmp_path / "my_tool"
        scaffold_cli_tool(p)
        toml = _read(p, "pyproject.toml")
        assert "my-tool" in toml
        assert "my_tool.cli.main:cli" in toml

    def test_logger_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "my_tool"
        scaffold_cli_tool(p)
        src = _read(p, "utils/logger.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_idempotent(self, tmp_path):
        p = tmp_path / "my_tool"
        r1 = scaffold_cli_tool(p)
        r2 = scaffold_cli_tool(p)
        assert {e.path for e in r1.created} == {e.path for e in r2.skipped}


# ---------------------------------------------------------------------------
# scaffold_pipeline
# ---------------------------------------------------------------------------

class TestScaffoldPipeline:
    def test_creates_expected_dirs(self, tmp_path):
        result = scaffold_pipeline(tmp_path / "proj")
        dirs = _dirs(result)
        for d in ("pipeline", "schemas", "data/input", "data/staging", "data/output",
                  "utils", "tests", "logs"):
            assert d in dirs, f"dir {d!r} missing"

    def test_creates_expected_files(self, tmp_path):
        result = scaffold_pipeline(tmp_path / "proj")
        files = _files(result)
        for f in (
            "pipeline/__init__.py",
            "pipeline/extract.py",
            "pipeline/transform.py",
            "pipeline/enrich.py",
            "pipeline/load.py",
            "pipeline/runner.py",
            "schemas/__init__.py",
            "schemas/records.py",
            "utils/logger.py",
            "tests/test_pipeline.py",
            ".env",
        ):
            assert f in files, f"file {f!r} missing"

    def test_no_llm_by_default(self, tmp_path):
        result = scaffold_pipeline(tmp_path / "proj")
        assert "utils/llm.py" not in _files(result)

    def test_include_llm(self, tmp_path):
        result = scaffold_pipeline(tmp_path / "proj", include_llm=True)
        assert "utils/llm.py" in _files(result)

    def test_env_has_logger_vars(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p)
        env = _read(p, ".env")
        for var in ("LOG_DIR", "LOG_LEVEL"):
            assert var in env

    def test_env_has_llm_vars_when_requested(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p, include_llm=True)
        env = _read(p, ".env")
        for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_MODE"):
            assert var in env

    def test_enrich_uses_llm_when_requested(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p, include_llm=True)
        src = _read(p, "pipeline/enrich.py")
        assert "from utils.llm import llm" in src

    def test_enrich_no_llm_by_default(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p)
        src = _read(p, "pipeline/enrich.py")
        assert "from utils.llm" not in src

    def test_logger_util_uses_infrakit_config(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p)
        src = _read(p, "utils/logger.py")
        assert "infrakit.core.config.loader" in src
        assert "os.getenv(" not in src

    def test_idempotent(self, tmp_path):
        p = tmp_path / "proj"
        r1 = scaffold_pipeline(p)
        r2 = scaffold_pipeline(p)
        assert {e.path for e in r1.created} == {e.path for e in r2.skipped}


# ---------------------------------------------------------------------------
# ScaffoldResult helpers
# ---------------------------------------------------------------------------

class TestScaffoldResult:
    def test_created_skipped_views(self, tmp_path):
        p = tmp_path / "proj"
        r1 = scaffold_basic(p)
        r2 = scaffold_basic(p)
        assert len(r1.created) > 0
        assert len(r1.skipped) == 0
        assert len(r2.created) == 0
        assert len(r2.skipped) > 0

    def test_project_dir_set(self, tmp_path):
        p = tmp_path / "proj"
        result = scaffold_basic(p)
        assert result.project_dir == p
