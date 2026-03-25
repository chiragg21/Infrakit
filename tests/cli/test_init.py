"""
tests/cli/test_init.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for ``ik init``.
"""

from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _init(cli, tmp_path, project="my_project", extra_args=None):
    args = ["init", project, "--dir", str(tmp_path)]
    if extra_args:
        args += extra_args
    return cli(args)


def _project(tmp_path, name="my_project") -> Path:
    return tmp_path / name


# ══════════════════════════════════════════════════════════════════════════════
# basic scaffolding
# ══════════════════════════════════════════════════════════════════════════════

class TestInitBasic:

    def test_exits_zero(self, cli, tmp_path):
        result = _init(cli, tmp_path)
        assert result.exit_code == 0

    def test_creates_project_dir(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert _project(tmp_path).is_dir()

    def test_creates_src(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "src").is_dir()

    def test_creates_src_init(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "src" / "__init__.py").exists()

    def test_creates_utils(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "utils").is_dir()

    def test_creates_utils_logger(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "utils" / "logger.py").exists()

    def test_creates_tests_dir(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "tests").is_dir()

    def test_creates_tests_init(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "tests" / "__init__.py").exists()

    def test_creates_readme(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "README.md").exists()

    def test_creates_gitignore(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / ".gitignore").exists()

    def test_default_config_is_env(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / ".env").exists()

    def test_default_deps_is_toml(self, cli, tmp_path):
        _init(cli, tmp_path)
        assert (_project(tmp_path) / "pyproject.toml").exists()

    def test_output_shows_created_items(self, cli, tmp_path):
        result = _init(cli, tmp_path)
        assert "+" in result.output

    def test_output_shows_project_name(self, cli, tmp_path):
        result = _init(cli, tmp_path)
        assert "my_project" in result.output

    def test_output_shows_next_steps(self, cli, tmp_path):
        result = _init(cli, tmp_path)
        assert "cd" in result.output


# ══════════════════════════════════════════════════════════════════════════════
# pyproject.toml content
# ══════════════════════════════════════════════════════════════════════════════

class TestInitPyproject:

    def test_contains_project_name(self, cli, tmp_path):
        _init(cli, tmp_path, "my_project")
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert 'name' in toml
        assert 'my_project' in toml

    def test_contains_default_version(self, cli, tmp_path):
        _init(cli, tmp_path)
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "0.1.0" in toml

    def test_custom_version(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--version", "2.3.4"])
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "2.3.4" in toml

    def test_custom_author(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--author", "Chirag"])
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "Chirag" in toml

    def test_custom_description(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--description", "My cool app"])
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "My cool app" in toml

    def test_no_build_system_block(self, cli, tmp_path):
        """pyproject.toml should not include [build-system] — general project, not a package."""
        _init(cli, tmp_path)
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "[build-system]" not in toml

    def test_contains_infrakit_dependency(self, cli, tmp_path):
        _init(cli, tmp_path)
        toml = (_project(tmp_path) / "pyproject.toml").read_text()
        assert "infrakit" in toml


# ══════════════════════════════════════════════════════════════════════════════
# config format option
# ══════════════════════════════════════════════════════════════════════════════

class TestInitConfigFormat:

    def test_yaml_config(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--config", "yaml"])
        assert (_project(tmp_path) / "config.yaml").exists()
        assert not (_project(tmp_path) / ".env").exists()

    def test_json_config(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--config", "json"])
        assert (_project(tmp_path) / "config.json").exists()

    def test_env_config_explicit(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--config", "env"])
        assert (_project(tmp_path) / ".env").exists()

    def test_invalid_config_format_exits_nonzero(self, cli, tmp_path):
        result = _init(cli, tmp_path, extra_args=["--config", "toml"])
        assert result.exit_code != 0

    def test_env_file_contains_placeholder(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--config", "env"])
        content = (_project(tmp_path) / ".env").read_text()
        assert "YOUR_VALUE_HERE" in content


# ══════════════════════════════════════════════════════════════════════════════
# deps option
# ══════════════════════════════════════════════════════════════════════════════

class TestInitDeps:

    def test_requirements_txt(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--deps", "requirements"])
        assert (_project(tmp_path) / "requirements.txt").exists()
        assert not (_project(tmp_path) / "pyproject.toml").exists()

    def test_requirements_contains_infrakit(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--deps", "requirements"])
        content = (_project(tmp_path) / "requirements.txt").read_text()
        assert "infrakit" in content

    def test_toml_explicit(self, cli, tmp_path):
        _init(cli, tmp_path, extra_args=["--deps", "toml"])
        assert (_project(tmp_path) / "pyproject.toml").exists()

    def test_invalid_deps_exits_nonzero(self, cli, tmp_path):
        result = _init(cli, tmp_path, extra_args=["--deps", "pipfile"])
        assert result.exit_code != 0

    def test_requirements_next_steps_hint(self, cli, tmp_path):
        result = _init(cli, tmp_path, extra_args=["--deps", "requirements"])
        assert "requirements.txt" in result.output


# ══════════════════════════════════════════════════════════════════════════════
# idempotency
# ══════════════════════════════════════════════════════════════════════════════

class TestInitIdempotency:

    def test_rerun_exits_zero(self, cli, tmp_path):
        _init(cli, tmp_path)
        result = _init(cli, tmp_path)
        assert result.exit_code == 0

    def test_rerun_does_not_overwrite_files(self, cli, tmp_path):
        _init(cli, tmp_path)
        readme = _project(tmp_path) / "README.md"
        readme.write_text("# Custom README\n")
        _init(cli, tmp_path)
        assert readme.read_text() == "# Custom README\n"

    def test_rerun_shows_skipped_items(self, cli, tmp_path):
        _init(cli, tmp_path)
        result = _init(cli, tmp_path)
        assert "~" in result.output

    def test_rerun_shows_nothing_new_message(self, cli, tmp_path):
        _init(cli, tmp_path)
        result = _init(cli, tmp_path)
        assert "up to date" in result.output.lower()

    def test_partial_project_fills_missing(self, cli, tmp_path):
        """If some files exist but others are missing, only missing ones are created."""
        _init(cli, tmp_path)
        readme = _project(tmp_path) / "README.md"
        readme.unlink()
        _init(cli, tmp_path)
        assert readme.exists()