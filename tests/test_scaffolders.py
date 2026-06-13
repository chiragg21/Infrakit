"""
tests/test_scaffolders.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for infrakit.scaffolder — all five templates.

Run with:  uv run pytest tests/test_scaffolders.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Package name and version correctness
# ---------------------------------------------------------------------------

class TestScaffoldPackageNames:
    """Every generated pyproject.toml must use python-infrakit-dev, not infrakit."""

    def _toml(self, tmp_path, scaffolder, **kwargs) -> str:
        p = tmp_path / "proj"
        scaffolder(p, **kwargs)
        return (p / "pyproject.toml").read_text(encoding="utf-8")

    def test_basic_uses_python_infrakit_dev(self, tmp_path):
        toml = self._toml(tmp_path, scaffold_basic)
        assert "python-infrakit-dev" in toml
        assert '"infrakit"' not in toml
        assert "'infrakit'" not in toml

    def test_ai_uses_python_infrakit_dev(self, tmp_path):
        toml = self._toml(tmp_path, scaffold_ai)
        assert "python-infrakit-dev" in toml

    def test_backend_uses_python_infrakit_dev(self, tmp_path):
        toml = self._toml(tmp_path, scaffold_backend)
        assert "python-infrakit-dev" in toml

    def test_cli_tool_uses_python_infrakit_dev(self, tmp_path):
        toml = self._toml(tmp_path, scaffold_cli_tool)
        assert "python-infrakit-dev" in toml

    def test_pipeline_uses_python_infrakit_dev(self, tmp_path):
        toml = self._toml(tmp_path, scaffold_pipeline)
        assert "python-infrakit-dev" in toml

    def test_pyproject_has_version_pin(self, tmp_path):
        """The infrakit dep should contain >= when the package is installed."""
        from infrakit.scaffolder.generator import _get_infrakit_version
        ver = _get_infrakit_version()
        if not ver:
            pytest.skip("python-infrakit-dev version not determinable in this env")
        toml = self._toml(tmp_path, scaffold_basic)
        assert f"python-infrakit-dev>={ver}" in toml

    def test_versioned_deps_contain_operator(self, tmp_path):
        """The _pkg_dep helper must return a >=X.Y.Z string when version known."""
        from infrakit.scaffolder.generator import _pkg_dep, _version_cache
        # seed cache with a known version so no HTTP call is made
        _version_cache["test-package-xyz"] = "1.2.3"
        dep = _pkg_dep("test-package-xyz")
        assert dep == "test-package-xyz>=1.2.3"

    def test_versioned_deps_no_version_fallback(self, tmp_path):
        """When version is unknown _pkg_dep returns just the package name."""
        from infrakit.scaffolder.generator import _pkg_dep, _version_cache
        _version_cache["unknown-package-abc"] = ""
        dep = _pkg_dep("unknown-package-abc")
        assert dep == "unknown-package-abc"


# ---------------------------------------------------------------------------
# Groq config in scaffolded projects
# ---------------------------------------------------------------------------

class TestScaffoldGroqConfig:
    """Groq must appear in generated LLM config and keys templates."""

    def test_keys_json_has_groq_keys(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        data = json.loads((p / "keys.json").read_text(encoding="utf-8"))
        assert "groq_keys" in data

    def test_basic_env_has_groq_api_key_when_llm_included(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p, include_llm=True)
        env = _read(p, ".env")
        assert "GROQ_API_KEY" in env

    def test_ai_env_has_groq_api_key(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        env = _read(p, ".env")
        assert "GROQ_API_KEY" in env

    def test_backend_env_has_groq_api_key(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        env = _read(p, ".env")
        assert "GROQ_API_KEY" in env

    def test_pipeline_env_has_groq_when_llm(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_pipeline(p, include_llm=True)
        env = _read(p, ".env")
        assert "GROQ_API_KEY" in env

    def test_llm_util_handles_groq_key(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        src = _read(p, "utils/llm.py")
        assert "groq_keys" in src
        assert "GROQ_API_KEY" in src
        assert "groq_model" in src

    def test_ai_pyproject_includes_groq(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_ai(p)
        toml = _read(p, "pyproject.toml")
        assert "groq" in toml

    def test_backend_pyproject_includes_groq(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_backend(p)
        toml = _read(p, "pyproject.toml")
        assert "groq" in toml

    def test_no_llm_env_does_not_have_groq_key(self, tmp_path):
        p = tmp_path / "proj"
        scaffold_basic(p, include_llm=False)
        env = _read(p, ".env")
        assert "GROQ_API_KEY" not in env
