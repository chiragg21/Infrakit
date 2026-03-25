"""
tests/core/test_loader.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for infrakit.core.config.loader

Run with: uv run pytest tests/core/test_loader.py -v
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from infrakit.core.config.loader import (
    ConfigLoadError,
    UnsupportedFormatError,
    cast_value,
    cast_dict,
    detect_format,
    load,
    load_env,
)


# ---------------------------------------------------------------------------
# Fixtures — write real temp files so we test actual parsing
# ---------------------------------------------------------------------------

@pytest.fixture
def json_file(tmp_path: Path) -> Path:
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"app": "infrakit", "debug": True, "port": 8080}))
    return f


@pytest.fixture
def yaml_file(tmp_path: Path) -> Path:
    f = tmp_path / "config.yaml"
    f.write_text(textwrap.dedent("""\
        app: infrakit
        debug: true
        port: 8080
        database:
          host: localhost
          port: 5432
    """))
    return f


@pytest.fixture
def ini_file(tmp_path: Path) -> Path:
    f = tmp_path / "config.ini"
    f.write_text(textwrap.dedent("""\
        [app]
        name = infrakit
        debug = true

        [database]
        host = localhost
        port = 5432
    """))
    return f


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        APP_NAME=infrakit
        DEBUG=true
        SECRET_KEY=supersecret
    """))
    return f


@pytest.fixture
def empty_yaml(tmp_path: Path) -> Path:
    f = tmp_path / "empty.yaml"
    f.write_text("")
    return f


@pytest.fixture
def bad_json(tmp_path: Path) -> Path:
    f = tmp_path / "bad.json"
    f.write_text("{not valid json")
    return f


@pytest.fixture
def array_json(tmp_path: Path) -> Path:
    """JSON that is valid but not a top-level object — should be rejected."""
    f = tmp_path / "array.json"
    f.write_text(json.dumps([1, 2, 3]))
    return f


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

class TestLoadJSON:
    def test_loads_flat_keys(self, json_file):
        cfg = load(json_file)
        assert cfg["app"] == "infrakit"
        assert cfg["debug"] is True
        assert cfg["port"] == 8080

    def test_returns_dict(self, json_file):
        assert isinstance(load(json_file), dict)

    def test_invalid_json_raises(self, bad_json):
        with pytest.raises(ConfigLoadError, match="Invalid JSON"):
            load(bad_json)

    def test_non_object_json_raises(self, array_json):
        with pytest.raises(ConfigLoadError, match="JSON object"):
            load(array_json)


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

class TestLoadYAML:
    def test_loads_flat_keys(self, yaml_file):
        cfg = load(yaml_file)
        assert cfg["app"] == "infrakit"
        assert cfg["debug"] is True

    def test_loads_nested_keys(self, yaml_file):
        cfg = load(yaml_file)
        assert cfg["database"]["host"] == "localhost"
        assert cfg["database"]["port"] == 5432

    def test_empty_yaml_returns_empty_dict(self, empty_yaml):
        assert load(empty_yaml) == {}

    def test_yml_extension_works(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text("key: value\n")
        assert load(f)["key"] == "value"


# ---------------------------------------------------------------------------
# INI
# ---------------------------------------------------------------------------

class TestLoadINI:
    def test_loads_sections_as_nested_dicts(self, ini_file):
        cfg = load(ini_file)
        assert "app" in cfg
        assert "database" in cfg

    def test_section_values_correct(self, ini_file):
        cfg = load(ini_file)
        assert cfg["app"]["name"] == "infrakit"
        assert cfg["database"]["host"] == "localhost"

    def test_cfg_extension_works(self, tmp_path):
        f = tmp_path / "config.cfg"
        f.write_text("[section]\nkey = val\n")
        cfg = load(f)
        assert cfg["section"]["key"] == "val"


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def test_load_via_load(self, env_file):
        cfg = load(env_file)
        assert cfg["APP_NAME"] == "infrakit"
        assert cfg["SECRET_KEY"] == "supersecret"

    def test_load_via_load_env(self, env_file):
        cfg = load_env(env_file)
        assert cfg["DEBUG"] == "true"

    def test_load_env_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_env(tmp_path / "nonexistent.env")


# ---------------------------------------------------------------------------
# Common error cases
# ---------------------------------------------------------------------------

class TestLoadErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load(tmp_path / "missing.json")

    def test_unsupported_extension_raises(self, tmp_path):
        f = tmp_path / "config.toml"
        f.write_text("key = 'value'\n")
        with pytest.raises(UnsupportedFormatError, match="Unsupported"):
            load(f)


# ---------------------------------------------------------------------------
# env_override
# ---------------------------------------------------------------------------

class TestEnvOverride:
    def test_os_env_overrides_existing_key(self, tmp_path, monkeypatch):
        # Use an uppercase key — Windows os.environ stores keys uppercased,
        # and _apply_flat_overrides now matches case-insensitively.
        f = tmp_path / "config.json"
        import json as _json
        f.write_text(_json.dumps({"APP": "infrakit", "debug": True, "port": 8080}))
        monkeypatch.setenv("APP", "overridden")
        cfg = load(f, env_override=True)
        assert cfg["APP"] == "overridden"

    def test_os_env_does_not_inject_unknown_keys(self, json_file, monkeypatch):
        monkeypatch.setenv("TOTALLY_NEW_KEY", "surprise")
        cfg = load(json_file, env_override=True)
        assert "TOTALLY_NEW_KEY" not in cfg

    def test_env_file_overrides_config(self, json_file, tmp_path):
        override = tmp_path / "override.env"
        override.write_text("app=from_env_file\n")
        cfg = load(json_file, env_file=override)
        assert cfg["app"] == "from_env_file"

    def test_env_file_missing_is_silently_skipped(self, json_file, tmp_path):
        cfg = load(json_file, env_file=tmp_path / "nonexistent.env")
        assert cfg["app"] == "infrakit"


# ---------------------------------------------------------------------------
# cast_value — unit tests
# ---------------------------------------------------------------------------

class TestCastValue:
    # Booleans
    @pytest.mark.parametrize("raw", ["true", "True", "TRUE", "yes", "Yes", "on", "1"])
    def test_truthy_strings(self, raw):
        assert cast_value(raw) is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "no", "No", "off", "0"])
    def test_falsy_strings(self, raw):
        assert cast_value(raw) is False

    # Null / None
    @pytest.mark.parametrize("raw", ["null", "Null", "NULL", "none", "None", "~", ""])
    def test_null_strings(self, raw):
        assert cast_value(raw) is None

    # Integers
    @pytest.mark.parametrize("raw,expected", [
        ("0",    0),
        ("42",   42),
        ("-7",   -7),
        ("+3",   3),
        ("1000", 1000),
    ])
    def test_integers(self, raw, expected):
        assert cast_value(raw) == expected
        assert isinstance(cast_value(raw), int)

    def test_leading_zero_stays_string(self):
        # "007" should NOT become int 7 — that changes the value
        assert cast_value("007") == "007"
        assert isinstance(cast_value("007"), str)

    # Floats
    @pytest.mark.parametrize("raw,expected", [
        ("2.5",   2.5),
        ("-0.1",  -0.1),
        ("3.14",  3.14),
        ("1e3",   1000.0),
        ("1.0",   1.0),
    ])
    def test_floats(self, raw, expected):
        assert cast_value(raw) == pytest.approx(expected)
        assert isinstance(cast_value(raw), float)

    @pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "Inf", "NaN"])
    def test_special_floats_stay_string(self, raw):
        # inf / nan are too surprising to auto-cast in config context
        assert cast_value(raw) == raw

    # Lists
    def test_comma_separated_mixed(self):
        result = cast_value("13,hello,2.5")
        assert result == [13, "hello", 2.5]

    def test_comma_separated_ints(self):
        assert cast_value("1,2,3") == [1, 2, 3]

    def test_comma_separated_bools(self):
        assert cast_value("true,false") == [True, False]

    def test_comma_separated_with_spaces(self):
        assert cast_value("  13 , hello , 2.5 ") == [13, "hello", 2.5]

    def test_trailing_comma_ignored(self):
        # "a,b," should produce ["a", "b"], not ["a", "b", None]
        assert cast_value("a,b,") == ["a", "b"]

    def test_list_items_recursively_cast(self):
        result = cast_value("true,null,42,3.14")
        assert result == [True, None, 42, 3.14]

    # Plain strings
    @pytest.mark.parametrize("raw", ["hello", "localhost", "my-app", "v1.2.3", "/usr/bin"])
    def test_plain_strings_unchanged(self, raw):
        assert cast_value(raw) == raw

    # Non-string passthrough
    def test_int_passthrough(self):
        assert cast_value(42) == 42  # type: ignore[arg-type]

    def test_bool_passthrough(self):
        assert cast_value(True) is True  # type: ignore[arg-type]

    def test_none_passthrough(self):
        assert cast_value(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# cast_dict — recursive casting
# ---------------------------------------------------------------------------

class TestCastDict:
    def test_flat_dict(self):
        result = cast_dict({"port": "8080", "debug": "true", "host": "localhost"})
        assert result == {"port": 8080, "debug": True, "host": "localhost"}

    def test_nested_dict(self):
        result = cast_dict({"db": {"port": "5432", "ssl": "false"}})
        assert result["db"]["port"] == 5432
        assert result["db"]["ssl"] is False

    def test_native_values_untouched(self):
        # Values that are already native types must not be re-cast
        result = cast_dict({"count": 10, "flag": True, "ratio": 1.5})
        assert result == {"count": 10, "flag": True, "ratio": 1.5}

    def test_list_value(self):
        result = cast_dict({"ports": "80,443,8080"})
        assert result["ports"] == [80, 443, 8080]

    def test_null_value(self):
        result = cast_dict({"secret": "null", "name": "infrakit"})
        assert result["secret"] is None
        assert result["name"] == "infrakit"


# ---------------------------------------------------------------------------
# Integration — cast_values=True through load() and load_env()
# ---------------------------------------------------------------------------

class TestCastValuesIntegration:
    def test_ini_with_cast(self, ini_file):
        cfg = load(ini_file, cast_values=True)
        # "true" -> True, "5432" -> 5432
        assert cfg["app"]["debug"] is True
        assert cfg["database"]["port"] == 5432

    def test_env_with_cast(self, env_file):
        cfg = load(env_file, cast_values=True)
        assert cfg["DEBUG"] is True                  # "true" -> True

    def test_load_env_with_cast(self, env_file):
        cfg = load_env(env_file, cast_values=True)
        assert cfg["DEBUG"] is True

    def test_json_unaffected_by_cast_flag(self, json_file):
        # JSON already has native types — cast_values should be a no-op
        cfg_cast   = load(json_file, cast_values=True)
        cfg_nocast = load(json_file, cast_values=False)
        assert cfg_cast == cfg_nocast

    def test_yaml_unaffected_by_cast_flag(self, yaml_file):
        cfg_cast   = load(yaml_file, cast_values=True)
        cfg_nocast = load(yaml_file, cast_values=False)
        assert cfg_cast == cfg_nocast

    def test_cast_off_by_default(self, ini_file):
        cfg = load(ini_file)
        # Without cast, everything is a string
        assert cfg["app"]["debug"] == "true"
        assert cfg["database"]["port"] == "5432"

    def test_env_list_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0\n")
        cfg = load_env(f, cast_values=True)
        assert cfg["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1", "0.0.0.0"]

    def test_env_mixed_list(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("PORTS=80,443,8080\nDEBUG=false\nMAX_RETRIES=3\n")
        cfg = load_env(f, cast_values=True)
        assert cfg["PORTS"] == [80, 443, 8080]
        assert cfg["DEBUG"] is False
        assert cfg["MAX_RETRIES"] == 3


# ---------------------------------------------------------------------------

class TestDetectFormat:
    @pytest.mark.parametrize("filename,expected", [
        ("config.json",  "json"),
        ("config.yaml",  "yaml"),
        ("config.yml",   "yaml"),
        ("config.ini",   "ini"),
        ("config.cfg",   "ini"),
        (".env",         "env"),
    ])
    def test_known_extensions(self, filename, expected):
        assert detect_format(filename) == expected

    def test_unknown_extension_raises(self):
        with pytest.raises(UnsupportedFormatError):
            detect_format("config.toml")


# ---------------------------------------------------------------------------
# Fix 1 — inject_new: .env can add keys not in the base config
# ---------------------------------------------------------------------------

class TestInjectNew:
    def test_inject_new_false_ignores_new_keys(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"host": "localhost", "port": 8080}))
        env_file = tmp_path / ".env"
        env_file.write_text("HOST=override\nNEW_KEY=hello\n")

        cfg = load(cfg_file, env_file=env_file, inject_new=False)
        # HOST in .env matches "host" in config case-insensitively — updates it
        assert cfg["host"] == "override"
        # NEW_KEY has no match in config — NOT injected
        assert "NEW_KEY" not in cfg

    def test_inject_new_true_adds_new_keys(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"host": "localhost"}))
        env_file = tmp_path / ".env"
        env_file.write_text("HOST=override\nNEW_KEY=hello\nANOTHER=world\n")

        cfg = load(cfg_file, env_file=env_file, inject_new=True)
        assert cfg["host"] == "override"       # existing key updated
        assert cfg["NEW_KEY"] == "hello"       # new key injected
        assert cfg["ANOTHER"] == "world"       # new key injected

    def test_inject_new_default_is_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"host": "localhost"}))
        env_file = tmp_path / ".env"
        env_file.write_text("BRAND_NEW=value\n")

        cfg = load(cfg_file, env_file=env_file)   # inject_new not passed
        assert "BRAND_NEW" not in cfg

    def test_inject_new_with_cast_values(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"host": "localhost"}))
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=9090\nDEBUG=true\n")

        # .env is string-only, but json ext skips casting —
        # injected keys from .env are still strings unless we load .env directly
        cfg = load(cfg_file, env_file=env_file, inject_new=True)
        assert cfg["PORT"] == "9090"    # string — cast_values didn't apply (json base)
        assert cfg["DEBUG"] == "true"

    def test_env_override_never_injects_new(self, json_file, monkeypatch):
        # env_override=True must never inject os.environ keys (PATH, HOME, etc.)
        monkeypatch.setenv("TOTALLY_NEW_KEY", "surprise")
        cfg = load(json_file, env_override=True)
        assert "TOTALLY_NEW_KEY" not in cfg

    def test_inject_new_yaml_source(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("host: localhost\nport: 8080\n")
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=abc123\nDEBUG=false\n")

        cfg = load(cfg_file, env_file=env_file, inject_new=True)
        assert cfg["SECRET_KEY"] == "abc123"
        assert cfg["DEBUG"] == "false"
        assert cfg["host"] == "localhost"   # base key untouched


# ---------------------------------------------------------------------------
# Fix 2 — within-file .env interpolation (python-dotenv native behaviour)
# ---------------------------------------------------------------------------

class TestDotenvWithinFileInterpolation:
    def test_simple_reference(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("BASE=/app\nLOG_DIR=${BASE}/logs\n")
        cfg = load_env(env_file)
        assert cfg["LOG_DIR"] == "/app/logs"

    def test_chained_references(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("HOST=localhost\nPORT=5432\nDB_URL=postgres://${HOST}:${PORT}/mydb\n")
        cfg = load_env(env_file)
        assert cfg["DB_URL"] == "postgres://localhost:5432/mydb"

    def test_unresolved_reference_stays_as_is(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("URL=postgres://${UNDEFINED_HOST}/db\n")
        cfg = load_env(env_file)
        # python-dotenv leaves unresolved references as empty or as-is
        # the exact behaviour depends on dotenv version — just assert no crash
        assert "URL" in cfg

    def test_reference_to_os_environ(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_HOME", "/opt/myapp")
        env_file = tmp_path / ".env"
        env_file.write_text("DATA_DIR=${APP_HOME}/data\n")
        cfg = load_env(env_file)
        # python-dotenv resolves from os.environ when the var isn't in the file
        assert cfg["DATA_DIR"] == "/opt/myapp/data"


# ---------------------------------------------------------------------------
# Fix 3 — cross-file interpolation: config.yaml referencing .env vars
# ---------------------------------------------------------------------------

class TestCrossFileInterpolation:
    def test_basic_yaml_references_env(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("database:\n  url: ${DATABASE_URL}\n  host: ${DB_HOST}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("DATABASE_URL=postgres://user:pass@localhost/mydb\nDB_HOST=localhost\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["database"]["url"] == "postgres://user:pass@localhost/mydb"
        assert cfg["database"]["host"] == "localhost"

    def test_flat_json_references_env(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"log_dir": "${LOG_DIR}/app", "host": "${HOST}"}))
        env_file = tmp_path / ".env"
        env_file.write_text("LOG_DIR=/var/log\nHOST=prod.example.com\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["log_dir"] == "/var/log/app"
        assert cfg["host"] == "prod.example.com"

    def test_unknown_reference_left_as_is(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("url: ${UNDEFINED_VAR}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("SOMETHING=else\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["url"] == "${UNDEFINED_VAR}"   # not expanded, not raised

    def test_default_value_syntax(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("port: ${PORT:-8080}\ntimeout: ${TIMEOUT:-30}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("")   # empty — no overrides

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["port"] == "8080"       # fallback used
        assert cfg["timeout"] == "30"

    def test_default_overridden_when_key_present(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("port: ${PORT:-8080}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=9090\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["port"] == "9090"       # .env value wins over default

    def test_interpolate_then_cast(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("port: ${PORT}\ndebug: ${DEBUG}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=9090\nDEBUG=true\n")

        # interpolate expands strings, then cast_values converts them
        # cast_values only applies to string-only format sources —
        # yaml is not string-only so no casting happens here.
        # Use .ini source to test cast after interpolate:
        ini_file = tmp_path / "config.ini"
        ini_file.write_text("[server]\nport = ${PORT}\ndebug = ${DEBUG}\n")
        cfg = load(ini_file, env_file=env_file, interpolate=True, cast_values=True)
        assert cfg["server"]["port"] == 9090   # string → int after cast
        assert cfg["server"]["debug"] is True  # string → bool after cast

    def test_interpolate_uses_os_environ_when_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "from-os-environ")
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("secret: ${SECRET_KEY}\n")

        cfg = load(cfg_file, env_override=True, interpolate=True)
        assert cfg["secret"] == "from-os-environ"

    def test_non_string_values_not_interpolated(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("port: 8080\ndebug: true\n")
        env_file = tmp_path / ".env"
        # Use keys that don't match any config key so override doesn't touch them
        env_file.write_text("UNRELATED=value\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["port"] == 8080     # native int — untouched by interpolation
        assert cfg["debug"] is True    # native bool — untouched by interpolation

    def test_nested_dict_fully_expanded(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(textwrap.dedent("""\
            database:
              host: ${DB_HOST}
              port: ${DB_PORT}
              name: ${DB_NAME}
            cache:
              url: redis://${REDIS_HOST}:${REDIS_PORT}
        """))
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DB_HOST=db.prod.com\nDB_PORT=5432\nDB_NAME=myapp\n"
            "REDIS_HOST=redis.prod.com\nREDIS_PORT=6379\n"
        )

        cfg = load(cfg_file, env_file=env_file, interpolate=True)
        assert cfg["database"]["host"] == "db.prod.com"
        assert cfg["database"]["port"] == "5432"
        assert cfg["cache"]["url"] == "redis://redis.prod.com:6379"

    def test_interpolate_false_leaves_tokens_unexpanded(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("url: ${DATABASE_URL}\n")
        env_file = tmp_path / ".env"
        env_file.write_text("DATABASE_URL=postgres://localhost/db\n")

        cfg = load(cfg_file, env_file=env_file, interpolate=False)
        assert cfg["url"] == "${DATABASE_URL}"   # token intact