"""
tests/core/test_exporter.py
Run with: uv run pytest tests/core/test_exporter.py -v
"""
from __future__ import annotations

import json as _json
import textwrap
import pytest

from infrakit.core.config.exporter import (
    PLACEHOLDER,
    export_dict,
    export_file,
    export_string,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_data():
    return {"HOST": "localhost", "PORT": 8080, "DEBUG": True}


@pytest.fixture
def nested_data():
    return {
        "app":      {"name": "infrakit", "debug": True},
        "database": {"host": "localhost", "port": 5432},
    }


@pytest.fixture
def env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DATABASE_URL=postgres://user:pass@localhost/db\nPORT=5432\nDEBUG=true\n")
    return f


@pytest.fixture
def yaml_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(textwrap.dedent("""\
        host: localhost
        port: 8080
        database:
          name: mydb
          ssl: false
    """))
    return f


# ---------------------------------------------------------------------------
# export_dict — env
# ---------------------------------------------------------------------------

class TestExportDictEnv:
    def test_all_keys_present(self, flat_data):
        result = export_dict(flat_data, to_format="env")
        for key in flat_data:
            assert f"{key}=" in result

    def test_all_values_replaced(self, flat_data):
        result = export_dict(flat_data, to_format="env")
        assert result.count(PLACEHOLDER) == len(flat_data)

    def test_real_values_absent(self, flat_data):
        result = export_dict(flat_data, to_format="env")
        assert "localhost" not in result
        assert "8080" not in result

    def test_nested_dict_flattened(self, nested_data):
        result = export_dict(nested_data, to_format="env")
        assert "APP__NAME=" in result
        assert "DATABASE__HOST=" in result

    def test_nested_values_replaced(self, nested_data):
        result = export_dict(nested_data, to_format="env")
        assert "localhost" not in result
        assert "infrakit" not in result

    def test_no_hint_comments(self, flat_data):
        result = export_dict(flat_data, to_format="env")
        assert "e.g." not in result


# ---------------------------------------------------------------------------
# export_dict — ini
# ---------------------------------------------------------------------------

class TestExportDictIni:
    def test_sections_preserved(self, nested_data):
        result = export_dict(nested_data, to_format="ini")
        assert "[app]" in result
        assert "[database]" in result

    def test_keys_preserved(self, nested_data):
        result = export_dict(nested_data, to_format="ini")
        assert "name = " in result
        assert "host = " in result

    def test_all_values_replaced(self, nested_data):
        result = export_dict(nested_data, to_format="ini")
        assert "localhost" not in result
        assert PLACEHOLDER in result

    def test_flat_data_no_sections(self, flat_data):
        result = export_dict(flat_data, to_format="ini")
        assert "[" not in result
        assert PLACEHOLDER in result

    def test_no_hint_comments(self, nested_data):
        result = export_dict(nested_data, to_format="ini")
        assert "e.g." not in result


# ---------------------------------------------------------------------------
# export_dict — json
# ---------------------------------------------------------------------------

class TestExportDictJson:
    def test_valid_json(self, flat_data):
        result = export_dict(flat_data, to_format="json")
        parsed = _json.loads(result)
        assert isinstance(parsed, dict)

    def test_keys_preserved(self, flat_data):
        result = export_dict(flat_data, to_format="json")
        parsed = _json.loads(result)
        for key in flat_data:
            assert key in parsed

    def test_all_values_replaced(self, flat_data):
        result = export_dict(flat_data, to_format="json")
        parsed = _json.loads(result)
        for v in parsed.values():
            assert v == PLACEHOLDER

    def test_nested_structure_preserved(self, nested_data):
        result = export_dict(nested_data, to_format="json")
        parsed = _json.loads(result)
        assert "app" in parsed
        assert "database" in parsed
        assert isinstance(parsed["app"], dict)

    def test_nested_values_replaced(self, nested_data):
        result = export_dict(nested_data, to_format="json")
        parsed = _json.loads(result)
        assert parsed["app"]["name"] == PLACEHOLDER
        assert parsed["database"]["host"] == PLACEHOLDER

    def test_real_values_absent(self, flat_data):
        result = export_dict(flat_data, to_format="json")
        assert "localhost" not in result
        assert "8080" not in result


# ---------------------------------------------------------------------------
# export_dict — yaml
# ---------------------------------------------------------------------------

class TestExportDictYaml:
    def test_keys_in_output(self, flat_data):
        result = export_dict(flat_data, to_format="yaml")
        for key in flat_data:
            assert key in result

    def test_placeholder_in_output(self, flat_data):
        result = export_dict(flat_data, to_format="yaml")
        assert PLACEHOLDER in result

    def test_real_values_absent(self, flat_data):
        result = export_dict(flat_data, to_format="yaml")
        assert "localhost" not in result

    def test_nested_structure_preserved(self, nested_data):
        result = export_dict(nested_data, to_format="yaml")
        assert "app:" in result
        assert "database:" in result

    def test_header_comment_present(self, flat_data):
        result = export_dict(flat_data, to_format="yaml")
        assert result.startswith("#")


# ---------------------------------------------------------------------------
# export_dict — invalid format
# ---------------------------------------------------------------------------

class TestExportDictErrors:
    def test_unsupported_format_raises(self, flat_data):
        with pytest.raises(ValueError, match="Unsupported format"):
            export_dict(flat_data, to_format="toml")


# ---------------------------------------------------------------------------
# export_string
# ---------------------------------------------------------------------------

class TestExportString:
    def test_env_to_env(self):
        raw = "HOST=localhost\nPORT=8080\n"
        result = export_string(raw, from_format="env", to_format="env")
        assert "HOST=" in result
        assert PLACEHOLDER in result
        assert "localhost" not in result

    def test_env_to_json(self):
        raw = "PORT=8080\nDEBUG=true\n"
        result = export_string(raw, from_format="env", to_format="json")
        parsed = _json.loads(result)
        assert parsed["PORT"] == PLACEHOLDER
        assert parsed["DEBUG"] == PLACEHOLDER

    def test_env_to_ini(self):
        raw = "HOST=localhost\nPORT=8080\n"
        result = export_string(raw, from_format="env", to_format="ini")
        assert PLACEHOLDER in result
        assert "localhost" not in result

    def test_env_to_yaml(self):
        raw = "HOST=localhost\n"
        result = export_string(raw, from_format="env", to_format="yaml")
        assert PLACEHOLDER in result
        assert "localhost" not in result

    def test_invalid_from_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            export_string("x=1", from_format="toml", to_format="env")

    def test_invalid_to_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            export_string("x=1", from_format="env", to_format="toml")


# ---------------------------------------------------------------------------
# export_file
# ---------------------------------------------------------------------------

class TestExportFile:
    def test_env_to_env_example(self, env_file, tmp_path):
        target = tmp_path / ".env.example"
        export_file(env_file, target, to_format="env")
        content = target.read_text()
        assert "DATABASE_URL=" in content
        assert PLACEHOLDER in content
        assert "postgres" not in content

    def test_env_to_json(self, env_file, tmp_path):
        target = tmp_path / "config.example.json"
        export_file(env_file, target, to_format="json")
        parsed = _json.loads(target.read_text())
        assert all(v == PLACEHOLDER for v in parsed.values())

    def test_env_to_yaml(self, env_file, tmp_path):
        target = tmp_path / "config.example.yaml"
        export_file(env_file, target, to_format="yaml")
        content = target.read_text()
        assert PLACEHOLDER in content
        assert "postgres" not in content

    def test_yaml_to_ini(self, yaml_file, tmp_path):
        target = tmp_path / "config.example.ini"
        export_file(yaml_file, target, to_format="ini")
        content = target.read_text()
        assert PLACEHOLDER in content
        assert "localhost" not in content

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            export_file(tmp_path / "ghost.env", tmp_path / "out.env", to_format="env")

    def test_existing_target_raises_without_overwrite(self, env_file, tmp_path):
        target = tmp_path / ".env.example"
        target.write_text("old")
        with pytest.raises(FileExistsError):
            export_file(env_file, target, to_format="env")

    def test_overwrite_replaces_target(self, env_file, tmp_path):
        target = tmp_path / ".env.example"
        target.write_text("old content")
        export_file(env_file, target, to_format="env", overwrite=True)
        assert "old content" not in target.read_text()
        assert PLACEHOLDER in target.read_text()

    def test_to_format_is_required(self, env_file, tmp_path):
        # to_format has no default — calling without it is a TypeError
        with pytest.raises(TypeError):
            export_file(env_file, tmp_path / "out", overwrite=True)