from __future__ import annotations
import json as _json
import textwrap
import pytest
from infrakit.core.config.converter import (
    ConversionError, ConversionWarning,
    convert_dict, convert_file,
)

# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_data():
    return {"host": "localhost", "port": 8080, "debug": True}


@pytest.fixture
def nested_data():
    return {
        "app":      {"name": "infrakit", "debug": True},
        "database": {"host": "localhost", "port": 5432},
    }


@pytest.fixture
def list_data():
    return {"hosts": ["localhost", "127.0.0.1"], "port": 80}


@pytest.fixture
def json_file(tmp_path, flat_data):
    f = tmp_path / "config.json"
    f.write_text(_json.dumps(flat_data))
    return f


@pytest.fixture
def yaml_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(textwrap.dedent("""\
        app:
          name: infrakit
          debug: true
        database:
          host: localhost
          port: 5432
    """))
    return f


# ---------------------------------------------------------------------------
# convert_dict — lossless conversions
# ---------------------------------------------------------------------------

class TestConvertDictLossless:
    def test_json_to_yaml(self, flat_data):
        output, warnings = convert_dict(flat_data, from_format="json", to_format="yaml")
        assert "host" in output
        assert "localhost" in output
        assert warnings == []

    def test_yaml_to_json(self, nested_data):
        output, warnings = convert_dict(nested_data, from_format="yaml", to_format="json")
        parsed = _json.loads(output)
        assert parsed["app"]["name"] == "infrakit"
        assert warnings == []

    def test_json_to_json_roundtrip(self, flat_data):
        output, warnings = convert_dict(flat_data, from_format="json", to_format="json")
        parsed = _json.loads(output)
        assert parsed["port"] == 8080
        assert warnings == []


class TestConvertDictLossy:
    def test_list_to_ini_is_stringified(self, list_data):
        output, warnings = convert_dict(list_data, from_format="json", to_format="ini")
        assert len(warnings) == 1
        assert isinstance(warnings[0], ConversionWarning)
        assert warnings[0].key.endswith("hosts")
        # The stringified value should be comma-joined
        assert "localhost" in warnings[0].stringified
        assert "127.0.0.1" in warnings[0].stringified

    def test_list_to_env_is_stringified(self, list_data):
        output, warnings = convert_dict(list_data, from_format="json", to_format="env")
        assert any(w.key.endswith("hosts") for w in warnings)
        assert "localhost" in output

    def test_warning_str_is_readable(self, list_data):
        _, warnings = convert_dict(list_data, from_format="json", to_format="ini")
        assert "Lossy" in str(warnings[0])
        assert "hosts" in str(warnings[0])


class TestConvertDictErrors:
    def test_unknown_source_format(self, flat_data):
        with pytest.raises(ConversionError, match="Unknown source"):
            convert_dict(flat_data, from_format="toml", to_format="json")

    def test_unknown_target_format(self, flat_data):
        with pytest.raises(ConversionError, match="Unknown target"):
            convert_dict(flat_data, from_format="json", to_format="toml")


# ---------------------------------------------------------------------------
# convert_file
# ---------------------------------------------------------------------------

class TestConvertFile:
    def test_json_to_yaml_file(self, json_file, tmp_path):
        target = tmp_path / "out.yaml"
        warnings = convert_file(json_file, target)
        assert target.exists()
        content = target.read_text()
        assert "host" in content
        assert warnings == []

    def test_yaml_to_json_file(self, yaml_file, tmp_path):
        target = tmp_path / "out.json"
        convert_file(yaml_file, target)
        parsed = _json.loads(target.read_text())
        assert parsed["app"]["name"] == "infrakit"

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            convert_file(tmp_path / "ghost.json", tmp_path / "out.yaml")

    def test_existing_target_raises_without_overwrite(self, json_file, tmp_path):
        target = tmp_path / "out.yaml"
        target.write_text("existing")
        with pytest.raises(FileExistsError):
            convert_file(json_file, target)

    def test_overwrite_flag_replaces_file(self, json_file, tmp_path):
        target = tmp_path / "out.yaml"
        target.write_text("old content")
        convert_file(json_file, target, overwrite=True)
        assert "host" in target.read_text()

    def test_env_file_dotfile_inferred(self, tmp_path, flat_data):
        src = tmp_path / "config.json"
        src.write_text(_json.dumps(flat_data))
        target = tmp_path / ".env"
        convert_file(src, target)
        content = target.read_text()
        assert "PORT" in content or "port" in content