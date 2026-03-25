"""
tests/cli/conftest.py
~~~~~~~~~~~~~~~~~~~~~
Shared fixtures for CLI tests.
"""

import pytest
from typer.testing import CliRunner

from infrakit.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    """Typer CLI runner. Output (stdout + stderr) available via result.output."""
    return CliRunner()


@pytest.fixture
def cli(runner):
    """Convenience wrapper: call cli(['config', 'convert', ...]) directly."""
    def _invoke(*args, **kwargs):
        return runner.invoke(app, *args, **kwargs)
    return _invoke


# ── sample config files ───────────────────────────────────────────────────────

@pytest.fixture
def env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("APP_ENV=development\nAPP_DEBUG=false\nAPP_SECRET=s3cr3t\n")
    return f


@pytest.fixture
def yaml_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("app:\n  env: development\n  debug: false\n  secret: s3cr3t\n")
    return f


@pytest.fixture
def json_file(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"app": {"env": "development", "debug": false, "secret": "s3cr3t"}}\n')
    return f


@pytest.fixture
def log_dir(tmp_path):
    """A logs directory with some dummy files at varying ages."""
    import time
    d = tmp_path / "logs"
    d.mkdir()

    # fresh file — should never be deleted
    fresh = d / "today.log"
    fresh.write_text("fresh log\n")

    # old file — simulate by setting mtime to 10 days ago
    old = d / "old.log"
    old.write_text("old log\n")
    old_mtime = time.time() - (10 * 86400)
    import os
    os.utime(old, (old_mtime, old_mtime))

    return d