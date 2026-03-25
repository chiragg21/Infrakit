"""
tests/cli/test_module.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for ``ik module create``, ``ik module delete``, and ``ik module tree``.
"""

import os
import re
import time
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# module create
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleCreate:

    def _create(self, cli, tmp_path, path, extra_args=None):
        """Helper — runs create from tmp_path as cwd."""
        args = ["module", "create", path] + (extra_args or [])
        return cli(args, catch_exceptions=False, env={"PWD": str(tmp_path)})

    # ── flat module ───────────────────────────────────────────────────────────

    def test_creates_directory(self, runner, tmp_path):
        from infrakit.cli.main import app
        result = runner.invoke(app, ["module", "create", "utils"], catch_exceptions=False,
                               env={**os.environ, "PWD": str(tmp_path)})
        # CliRunner doesn't change cwd; use os.chdir approach instead
        # We test through the generator directly for cwd-sensitive commands
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "create", "utils"])
            assert result.exit_code == 0
            assert (tmp_path / "utils").is_dir()
        finally:
            os.chdir(original)

    def test_creates_init_py_by_default(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "utils"])
            assert (tmp_path / "utils" / "__init__.py").exists()
        finally:
            os.chdir(original)

    def test_no_init_flag_skips_init_py(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "utils", "--no-init"])
            assert (tmp_path / "utils").is_dir()
            assert not (tmp_path / "utils" / "__init__.py").exists()
        finally:
            os.chdir(original)

    # ── nested modules ────────────────────────────────────────────────────────

    def test_creates_nested_dirs(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "core/models"])
            assert (tmp_path / "core").is_dir()
            assert (tmp_path / "core" / "models").is_dir()
        finally:
            os.chdir(original)

    def test_nested_creates_init_in_both(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "core/models"])
            assert (tmp_path / "core" / "__init__.py").exists()
            assert (tmp_path / "core" / "models" / "__init__.py").exists()
        finally:
            os.chdir(original)

    def test_no_init_parents_skips_parent_init(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "core/models", "--no-init-parents"])
            assert not (tmp_path / "core" / "__init__.py").exists()
            assert (tmp_path / "core" / "models" / "__init__.py").exists()
        finally:
            os.chdir(original)

    def test_deeply_nested(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "create", "a/b/c"])
            assert result.exit_code == 0
            assert (tmp_path / "a" / "b" / "c").is_dir()
        finally:
            os.chdir(original)

    def test_existing_dir_skipped_not_error(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            (tmp_path / "utils").mkdir()
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "create", "utils"])
            assert result.exit_code == 0
            assert "~" in result.output  # skipped marker
        finally:
            os.chdir(original)

    def test_init_py_content_has_docstring(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            r.invoke(app, ["module", "create", "utils"])
            content = (tmp_path / "utils" / "__init__.py").read_text()
            assert '"""' in content
        finally:
            os.chdir(original)


# ══════════════════════════════════════════════════════════════════════════════
# module delete
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleDelete:

    def test_deletes_directory(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            target = tmp_path / "old_module"
            target.mkdir()
            (target / "foo.py").write_text("")
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "delete", "old_module", "--no-confirm"])
            assert result.exit_code == 0
            assert not target.exists()
        finally:
            os.chdir(original)

    def test_success_message(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            (tmp_path / "old_module").mkdir()
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "delete", "old_module", "--no-confirm"])
            assert "Deleted" in result.output
        finally:
            os.chdir(original)

    def test_missing_path_exits_nonzero(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "delete", "nonexistent", "--no-confirm"])
            assert result.exit_code != 0
        finally:
            os.chdir(original)

    def test_shows_file_count_before_delete(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            d = tmp_path / "mod"
            d.mkdir()
            (d / "a.py").write_text("")
            (d / "b.py").write_text("")
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "delete", "mod"], input="y\n")
            assert "2" in result.output
        finally:
            os.chdir(original)

    def test_nested_delete(self, tmp_path):
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            nested = tmp_path / "core" / "models"
            nested.mkdir(parents=True)
            (nested / "user.py").write_text("")
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "delete", "core/models", "--no-confirm"])
            assert result.exit_code == 0
            assert not nested.exists()
            assert (tmp_path / "core").exists()  # parent preserved
        finally:
            os.chdir(original)


# ══════════════════════════════════════════════════════════════════════════════
# module tree
# ══════════════════════════════════════════════════════════════════════════════

def _make_project(tmp_path: Path) -> Path:
    """Create a small project structure for tree tests."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "logger.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / ".env").write_text("APP_SECRET=s3cr3t\n")
    (tmp_path / "README.md").write_text("# Test\n")
    # gitignored stuff
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-313.pyc").write_text("")
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "v").mkdir()
    return tmp_path


def _make_gitignore(tmp_path: Path, patterns: list[str]) -> None:
    (tmp_path / ".gitignore").write_text("\n".join(patterns) + "\n")


class TestModuleTree:

    def _tree(self, runner, path, extra_args=None):
        from infrakit.cli.main import app
        args = ["module", "tree", str(path)] + (extra_args or [])
        return runner.invoke(app, args)

    def test_exits_zero(self, runner, tmp_path):
        _make_project(tmp_path)
        result = self._tree(runner, tmp_path)
        assert result.exit_code == 0

    def test_shows_root_dir_name(self, runner, tmp_path):
        _make_project(tmp_path)
        result = self._tree(runner, tmp_path)
        assert tmp_path.name in result.output

    def test_shows_known_files(self, runner, tmp_path):
        _make_project(tmp_path)
        result = self._tree(runner, tmp_path)
        assert "logger.py" in result.output
        assert "README.md" in result.output

    def test_shows_summary_line(self, runner, tmp_path):
        _make_project(tmp_path)
        result = self._tree(runner, tmp_path)
        assert "director" in result.output  # "directory" or "directories"
        assert "file" in result.output

    def test_missing_path_exits_nonzero(self, runner, tmp_path):
        result = self._tree(runner, tmp_path / "nope")
        assert result.exit_code != 0

    # ── gitignore filtering ───────────────────────────────────────────────────

    def test_hides_gitignored_by_default(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["__pycache__/"])
        result = self._tree(runner, tmp_path)
        # __pycache__ should not appear as a visible entry
        assert "__pycache__" not in result.output

    def test_show_ignored_reveals_hidden(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["__pycache__/"])
        result = self._tree(runner, tmp_path, ["--show-ignored"])
        assert "__pycache__" in result.output

    def test_show_ignored_marks_as_ignored(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["__pycache__/"])
        result = self._tree(runner, tmp_path, ["--show-ignored"])
        assert "ignored" in result.output

    def test_no_gitignore_shows_everything(self, runner, tmp_path):
        _make_project(tmp_path)
        # no .gitignore — only .git is auto-ignored
        result = self._tree(runner, tmp_path)
        assert "__pycache__" in result.output

    def test_dot_git_always_hidden(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, [])
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = self._tree(runner, tmp_path)
        # Strip ANSI escape codes before checking — Typer injects them between
        # tree chars and filenames, so "── .git" won't match raw output.
        # ".gitignore" in the summary is fine; we only care ".git" isn't a tree entry.
        ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
        clean = ansi_escape.sub("", result.output)
        tree_entries = [
            line for line in clean.splitlines()
            if any(c in line for c in ("├──", "└──", "│"))
        ]
        assert not any(
            entry.strip().endswith(".git") or entry.strip().endswith(".git/")
            for entry in tree_entries
        )

    # ── globstar patterns ─────────────────────────────────────────────────────

    def test_globstar_pattern_hides_nested(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["**/.pytest_cache/"])
        result = self._tree(runner, tmp_path)
        assert ".pytest_cache" not in result.output

    def test_globstar_pyc_pattern(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["**/*.pyc"])
        result = self._tree(runner, tmp_path)
        assert ".pyc" not in result.output

    def test_summary_gitignore_note(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["__pycache__/"])
        result = self._tree(runner, tmp_path)
        assert "gitignore" in result.output.lower()

    def test_summary_no_gitignore_note_when_show_ignored(self, runner, tmp_path):
        _make_project(tmp_path)
        _make_gitignore(tmp_path, ["__pycache__/"])
        result = self._tree(runner, tmp_path, ["--show-ignored"])
        # the "gitignore applied" note should not appear when --show-ignored is on
        assert "gitignore applied" not in result.output.lower()

    # ── defaults to cwd ───────────────────────────────────────────────────────

    def test_defaults_to_cwd(self, tmp_path):
        _make_project(tmp_path)
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            from infrakit.cli.main import app
            from typer.testing import CliRunner
            r = CliRunner()
            result = r.invoke(app, ["module", "tree"])
            assert result.exit_code == 0
            assert "logger.py" in result.output
        finally:
            os.chdir(original)