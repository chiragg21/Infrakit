"""
tests/cli/test_config.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for ``ik config convert`` and ``ik config export``.
"""

import json
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# config convert
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigConvert:

    def test_env_to_json(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        result = cli(["config", "convert", str(env_file), str(target)])
        assert result.exit_code == 0
        assert target.exists()
        data = json.loads(target.read_text())
        assert "APP_ENV" in data

    def test_env_to_yaml(self, cli, env_file, tmp_path):
        target = tmp_path / "out.yaml"
        result = cli(["config", "convert", str(env_file), str(target)])
        assert result.exit_code == 0
        assert target.exists()
        assert "APP_ENV" in target.read_text()

    def test_yaml_to_json(self, cli, yaml_file, tmp_path):
        target = tmp_path / "out.json"
        result = cli(["config", "convert", str(yaml_file), str(target)])
        assert result.exit_code == 0
        data = json.loads(target.read_text())
        assert "app" in data

    def test_output_contains_success_marker(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        result = cli(["config", "convert", str(env_file), str(target)])
        assert "Converted" in result.output

    def test_missing_source_exits_nonzero(self, cli, tmp_path):
        result = cli(["config", "convert", str(tmp_path / "nope.env"), str(tmp_path / "out.json")])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "not found" in result.output.lower()

    def test_target_exists_no_overwrite(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        target.write_text("{}")
        result = cli(["config", "convert", str(env_file), str(target)])
        assert result.exit_code != 0
        assert "overwrite" in result.output.lower() or "overwrite" in result.output.lower()

    def test_target_exists_with_overwrite_flag(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        target.write_text("{}")
        result = cli(["config", "convert", str(env_file), str(target), "--overwrite"])
        assert result.exit_code == 0
        # file should now have real content
        data = json.loads(target.read_text())
        assert data  # not empty

    def test_overwrite_short_flag(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        target.write_text("{}")
        result = cli(["config", "convert", str(env_file), str(target), "-y"])
        assert result.exit_code == 0


# ══════════════════════════════════════════════════════════════════════════════
# config export
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigExport:

    # ── stdout mode (no target) ───────────────────────────────────────────────

    def test_stdout_env_format(self, cli, env_file):
        result = cli(["config", "export", str(env_file), "--format", "env"])
        assert result.exit_code == 0
        assert "YOUR_VALUE_HERE" in result.output

    def test_stdout_json_format(self, cli, env_file, tmp_path):
        target = tmp_path / "out.json"
        result = cli(["config", "export", str(env_file), str(target), "--format", "json"])
        assert result.exit_code == 0
        assert target.exists()
        data = json.loads(target.read_text())
        assert data
        assert all(v == "YOUR_VALUE_HERE" for v in data.values())

    def test_stdout_yaml_format(self, cli, yaml_file):
        result = cli(["config", "export", str(yaml_file), "--format", "yaml"])
        assert result.exit_code == 0
        assert "YOUR_VALUE_HERE" in result.output

    def test_stdout_no_real_values(self, cli, env_file):
        """Real secret should never appear in the exported output."""
        result = cli(["config", "export", str(env_file), "--format", "env"])
        assert "s3cr3t" not in result.output

    def test_stdout_short_format_flag(self, cli, env_file):
        result = cli(["config", "export", str(env_file), "-f", "env"])
        assert result.exit_code == 0
        assert "YOUR_VALUE_HERE" in result.output

    # ── file mode (target given) ──────────────────────────────────────────────

    def test_file_mode_creates_target(self, cli, env_file, tmp_path):
        target = tmp_path / "template.env"
        result = cli(["config", "export", str(env_file), str(target), "--format", "env"])
        assert result.exit_code == 0
        assert target.exists()
        assert "YOUR_VALUE_HERE" in target.read_text()

    def test_file_mode_no_real_values(self, cli, env_file, tmp_path):
        target = tmp_path / "template.env"
        cli(["config", "export", str(env_file), str(target), "--format", "env"])
        assert "s3cr3t" not in target.read_text()

    def test_file_mode_success_message(self, cli, env_file, tmp_path):
        target = tmp_path / "template.env"
        result = cli(["config", "export", str(env_file), str(target), "--format", "env"])
        assert "Exported" in result.output

    def test_file_mode_target_exists_no_overwrite(self, cli, env_file, tmp_path):
        target = tmp_path / "template.env"
        target.write_text("existing")
        result = cli(["config", "export", str(env_file), str(target), "--format", "env"])
        assert result.exit_code != 0
        assert target.read_text() == "existing"

    def test_file_mode_target_exists_with_overwrite(self, cli, env_file, tmp_path):
        target = tmp_path / "template.env"
        target.write_text("existing")
        result = cli(["config", "export", str(env_file), str(target), "--format", "env", "--overwrite"])
        assert result.exit_code == 0
        assert "YOUR_VALUE_HERE" in target.read_text()

    # ── invalid inputs ────────────────────────────────────────────────────────

    def test_missing_source_exits_nonzero(self, cli, tmp_path):
        result = cli(["config", "export", str(tmp_path / "nope.env"), "--format", "env"])
        assert result.exit_code != 0

    def test_invalid_format_exits_nonzero(self, cli, env_file):
        result = cli(["config", "export", str(env_file), "--format", "xml"])
        assert result.exit_code != 0
        assert "xml" in result.output.lower() or "xml" in result.output.lower()

    def test_default_format_is_json(self, cli, env_file, tmp_path):
        """Omitting --format should use json as default and succeed."""
        target = tmp_path / "out.json"
        result = cli(["config", "export", str(env_file), str(target)])
        assert result.exit_code == 0
        assert target.exists()
        assert "YOUR_VALUE_HERE" in target.read_text()