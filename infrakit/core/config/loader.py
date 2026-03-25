"""
infrakit.core.config.loader
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Load configuration from JSON, YAML, INI, and .env files into a plain dict,
with optional type casting, env layering, and variable interpolation.

Usage:
    from infrakit.core.config.loader import load, load_env, cast_value

    cfg = load("config.yaml")
    env = load_env(".env")                              # strings only
    env = load_env(".env", cast_values=True)            # auto-cast types

    # Layer .env on top — inject brand-new keys too
    cfg = load("config.yaml", env_file=".env", inject_new=True)

    # Expand ${VAR} references in config values using .env as the source
    cfg = load("config.yaml", env_file=".env", interpolate=True)

    # All three together
    cfg = load("config.yaml", env_file=".env",
               inject_new=True, interpolate=True, cast_values=True)

Type casting rules (applied to string values only):
    "true" / "false"        -> bool
    "null" / "none" / ""   -> None
    "42"                    -> int
    "3.14"                  -> float
    "13,hello,2.5"          -> [13, "hello", 2.5]   (comma-separated list)
    anything else           -> str  (unchanged)

Variable interpolation:
    ${KEY} in any string value is replaced with the value of KEY from
    env_file (or os.environ if env_override=True). Unknown references are
    left as-is. Interpolation runs before casting.

    # config.yaml               # .env
    database:                   DATABASE_URL=postgres://user:pass@localhost/db
      url: ${DATABASE_URL}      LOG_DIR=/app/logs
    log_dir: ${LOG_DIR}/app

Within-file .env interpolation (handled natively by python-dotenv):
    BASE=/app
    LOG_DIR=${BASE}/logs        -> LOG_DIR=/app/logs

JSON and YAML already carry native types — casting is skipped for those.
"""

from __future__ import annotations

import json
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Any

# PyYAML is an optional dependency — raise a clear error if missing
try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# python-dotenv is an optional dependency
try:
    from dotenv import dotenv_values
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ConfigDict = dict[str, Any]

# Native Python scalar — what a cast_value() call can return
ScalarValue = bool | int | float | str | list[Any] | None

SUPPORTED_EXTENSIONS = {".json", ".yaml", ".yml", ".ini", ".cfg", ".env"}

# Formats whose values are always plain strings and benefit from casting.
# JSON and YAML already carry native types, so we skip casting there.
_STRING_ONLY_FORMATS = {".ini", ".cfg", ".env"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigLoadError(Exception):
    """Raised when a config file cannot be loaded or parsed."""


class UnsupportedFormatError(ConfigLoadError):
    """Raised when the file extension is not recognised."""


class MissingDependencyError(ConfigLoadError):
    """Raised when an optional dependency required for a format is not installed."""


# ---------------------------------------------------------------------------
# Type casting
# ---------------------------------------------------------------------------

#: Sentinel used internally so cast_value() can distinguish "the value was
#: the empty string" from "nothing was passed".
_MISSING = object()

# Boolean literals — matched case-insensitively
_TRUE_VALUES  = {"true", "yes", "on",  "1"}
_FALSE_VALUES = {"false", "no",  "off", "0"}
_NULL_VALUES  = {"null", "none", "~"}


def cast_value(value: str) -> ScalarValue:
    """Cast a single string value to the most specific Python type.

    Casting priority (first match wins):

    1. Empty string              -> ``None``
    2. Boolean literals          -> ``bool``  (true/false/yes/no/on/off/1/0)
    3. Null literals             -> ``None``  (null/none/~)
    4. Integer                  -> ``int``
    5. Float                    -> ``float``
    6. Comma-separated list     -> ``list``  (each item is recursively cast)
    7. Fallback                 -> ``str``   (unchanged)

    Parameters
    ----------
    value:
        A string, as produced by INI or .env parsers.

    Returns
    -------
    ScalarValue
        The cast Python value.

    Examples
    --------
    >>> cast_value("true")
    True
    >>> cast_value("3.14")
    3.14
    >>> cast_value("42")
    42
    >>> cast_value("null")
    None
    >>> cast_value("")
    None
    >>> cast_value("13,hello,2.5")
    [13, 'hello', 2.5]
    >>> cast_value("hello")
    'hello'
    """
    if not isinstance(value, str):
        # Already a native type (e.g. from YAML) — leave it alone
        return value  # type: ignore[return-value]

    stripped = value.strip()

    # 1. Empty string -> None
    if stripped == "":
        return None

    lower = stripped.lower()

    # 2. Boolean
    if lower in _TRUE_VALUES:
        return True
    if lower in _FALSE_VALUES:
        return False

    # 3. Null
    if lower in _NULL_VALUES:
        return None

    # 4. Integer (covers negatives; leading zeros like "007" stay as str)
    if _is_plain_integer(stripped):
        return int(stripped)

    # 5. Float — but only if it doesn't look like a leading-zero string.
    #    Without this guard, float("007") == 7.0 would slip through here
    #    after _is_plain_integer correctly rejects it as an int.
    candidate = stripped.lstrip("+-")
    has_leading_zero = len(candidate) > 1 and candidate[0] == "0" and candidate[1].isdigit()
    if not has_leading_zero:
        try:
            float_val = float(stripped)
            if not _is_special_float(stripped):
                return float_val
        except ValueError:
            pass

    # 6. Comma-separated list  (requires at least one comma)
    if "," in stripped:
        items = [item.strip() for item in stripped.split(",")]
        # Filter out empty items caused by trailing commas ("a,b,")
        return [cast_value(item) for item in items if item != ""]

    # 7. Fallback — plain string
    return stripped


def cast_dict(data: ConfigDict) -> ConfigDict:
    """Recursively cast all string leaf values in *data*.

    Nested dicts (e.g. INI sections) are traversed. Non-string values
    (already native types from JSON/YAML) are left untouched.

    Parameters
    ----------
    data:
        A config dict, potentially with nested dicts as values.

    Returns
    -------
    ConfigDict
        A new dict with cast values.
    """
    result: ConfigDict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = cast_dict(value)
        elif isinstance(value, str):
            result[key] = cast_value(value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Casting helpers
# ---------------------------------------------------------------------------

def _is_plain_integer(s: str) -> bool:
    """Return True only for decimal integers without leading zeros (except "0")."""
    if not s:
        return False
    candidate = s.lstrip("+-")
    if not candidate.isdigit():
        return False
    # Reject leading zeros: "007", "00", etc. — keep as string
    if len(candidate) > 1 and candidate[0] == "0":
        return False
    return True


def _is_special_float(s: str) -> bool:
    """Return True for "inf", "-inf", "nan" — we don't cast these."""
    lower = s.lower().lstrip("+-")
    return lower in {"inf", "infinity", "nan"}


# ---------------------------------------------------------------------------
# Internal format loaders
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> ConfigDict:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(f"Invalid JSON in '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigLoadError(
            f"Expected a JSON object at the top level in '{path}', "
            f"got {type(data).__name__}."
        )
    return data


def _load_yaml(path: Path) -> ConfigDict:
    if not _YAML_AVAILABLE:
        raise MissingDependencyError(
            "PyYAML is required to load YAML files. "
            "Install it with: pip install pyyaml"
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Invalid YAML in '{path}': {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigLoadError(
            f"Expected a YAML mapping at the top level in '{path}', "
            f"got {type(data).__name__}."
        )
    return data


def _load_ini(path: Path) -> ConfigDict:
    """
    Load an INI file and return a nested dict.

    Top-level keys without a section are stored under the special
    key ``"DEFAULT"`` by ConfigParser convention. Each section becomes
    a nested dict, e.g.:

        [database]
        host = localhost  ->  {"database": {"host": "localhost"}}
    """
    parser = ConfigParser()
    try:
        read = parser.read(path, encoding="utf-8")
    except Exception as exc:
        raise ConfigLoadError(f"Could not read INI file '{path}': {exc}") from exc

    if not read:
        raise ConfigLoadError(f"INI file not found or unreadable: '{path}'")

    result: ConfigDict = {}

    # DEFAULT section (key=value pairs outside any section header)
    if parser.defaults():
        result["DEFAULT"] = dict(parser.defaults())

    for section in parser.sections():
        # parser[section] includes DEFAULT keys too — use .options() to
        # grab only keys defined in this section
        result[section] = {
            key: parser.get(section, key)
            for key in parser.options(section)
            if key not in parser.defaults()
        }

    return result


def _load_dotenv(path: Path) -> ConfigDict:
    """
    Load a .env file and return a flat dict of string key→value pairs.
    Comments and blank lines are ignored by python-dotenv.
    """
    if not _DOTENV_AVAILABLE:
        raise MissingDependencyError(
            "python-dotenv is required to load .env files. "
            "Install it with: pip install python-dotenv"
        )
    values = dotenv_values(path)
    return dict(values)  # dotenv_values returns OrderedDict


# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------

_LOADERS = {
    ".json": _load_json,
    ".yaml": _load_yaml,
    ".yml":  _load_yaml,
    ".ini":  _load_ini,
    ".cfg":  _load_ini,
    ".env":  _load_dotenv,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load(
    path: str | Path,
    *,
    env_override: bool = False,
    env_file: str | Path | None = None,
    inject_new: bool = False,
    interpolate: bool = False,
    cast_values: bool = False,
) -> ConfigDict:
    """Load a config file and return its contents as a dict.

    Supports JSON, YAML (.yaml / .yml), INI (.ini / .cfg), and .env files.
    The format is inferred from the file extension.

    Parameters
    ----------
    path:
        Path to the config file.
    env_override:
        If ``True``, environment variables present in ``os.environ`` will
        override keys found in the config file (existing keys only,
        case-insensitive on Windows).
    env_file:
        Optional path to a ``.env`` file whose values are applied after
        the base config is loaded. Controlled by *inject_new*.
    inject_new:
        Only applies when *env_file* is set.

        ``False`` (default) — only keys already present in the base config
        are updated from the .env file. Keys unique to .env are ignored.
        This is safe for ``os.environ`` (avoids injecting PATH, HOME, etc).

        ``True`` — all keys from the .env file are merged in, including
        brand-new ones not present in the base config. Useful when .env
        is the primary source of runtime variables.
    interpolate:
        If ``True``, any ``${KEY}`` reference in a string value is expanded
        using the .env file values (or ``os.environ`` if *env_override* is
        True). The lookup order is: env_file first, then os.environ.

        Unknown ``${KEY}`` references are left as-is rather than raising.
        Interpolation runs before casting so cast_values sees expanded values.

        Example — config.yaml::

            database:
              url: ${DATABASE_URL}
            log_dir: ${LOG_DIR}/app

        With DATABASE_URL=postgres://... in .env, ``url`` becomes the
        full connection string after interpolation.
    cast_values:
        If ``True``, string values from string-only formats (INI, .env) are
        automatically cast to their most specific Python type. JSON and YAML
        already carry native types, so casting is skipped for those.

        Casting rules:

          - ``"true"`` / ``"false"`` → ``bool``
          - ``"null"`` / ``"none"`` / ``""`` → ``None``
          - ``"42"`` → ``int``
          - ``"2.5"`` → ``float``
          - ``"13,hello,2.5"`` → ``[13, "hello", 2.5]``
          - anything else → ``str``

    Returns
    -------
    ConfigDict
        A plain ``dict[str, Any]``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    UnsupportedFormatError
        If the file extension is not one of the supported formats.
    ConfigLoadError
        If the file exists but cannot be parsed.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: '{path}'")

    ext = _get_extension(path)
    loader_fn = _LOADERS.get(ext)
    if loader_fn is None:
        raise UnsupportedFormatError(
            f"Unsupported config format '{ext!r}'. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    config = loader_fn(path)

    # Collect the env vars that will be used for both override and interpolation
    env_vars: dict[str, str] = {}

    # Apply .env file — inject_new controls whether new keys are added.
    # case_insensitive=True matches "HOST" in .env to "host" in config.
    # When interpolate=True, skip overriding values that contain ${...}
    # templates — interpolation will expand them correctly instead.
    if env_file is not None:
        env_file = Path(env_file)
        if env_file.exists():
            dotenv_vals = _load_dotenv(env_file)
            env_vars.update(dotenv_vals)
            config = _apply_flat_overrides(
                config, dotenv_vals,
                case_insensitive=True,
                inject_new=inject_new,
                skip_templates=interpolate,
            )

    # Apply os.environ overrides — existing keys only, case-insensitive.
    # Same template-skip logic applies.
    if env_override:
        env_vars.update(os.environ)
        config = _apply_flat_overrides(
            config, dict(os.environ),
            case_insensitive=True,
            inject_new=False,
            skip_templates=interpolate,
        )

    # Expand ${KEY} and ${KEY:-default} references.
    # Run even when env_vars is empty — defaults (:-) work without any vars.
    if interpolate:
        config = _interpolate_dict(config, env_vars)

    # Cast string values for string-only formats (INI / .env).
    # JSON and YAML are skipped — they already have native types.
    if cast_values and ext in _STRING_ONLY_FORMATS:
        config = cast_dict(config)

    return config


def load_env(path: str | Path = ".env", *, cast_values: bool = False) -> ConfigDict:
    """Convenience wrapper — load a .env file directly.

    Parameters
    ----------
    path:
        Path to the .env file. Defaults to ``.env`` in the current directory.
    cast_values:
        If ``True``, string values are automatically cast to their most
        specific Python type. See :func:`load` for casting rules.

    Returns
    -------
    ConfigDict
        ``dict[str, Any]`` — strings if *cast_values* is False, native
        types otherwise.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f".env file not found: '{path}'")
    data = _load_dotenv(path)
    return cast_dict(data) if cast_values else data


def detect_format(path: str | Path) -> str:
    """Return the format name for a given file path.

    Useful for UI feedback and logging.

    Returns one of: ``"json"``, ``"yaml"``, ``"ini"``, ``"env"``.

    Raises
    ------
    UnsupportedFormatError
        If the extension is not recognised.
    """
    ext = _get_extension(Path(path))
    _FORMAT_NAMES = {
        ".json": "json",
        ".yaml": "yaml",
        ".yml":  "yaml",
        ".ini":  "ini",
        ".cfg":  "ini",
        ".env":  "env",
    }
    name = _FORMAT_NAMES.get(ext)
    if name is None:
        raise UnsupportedFormatError(
            f"Cannot detect format for extension '{ext}'."
        )
    return name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extension(path: Path) -> str:
    """Return the lowercase extension for *path*, handling dotfiles correctly.

    ``Path(".env").suffix`` returns ``""`` on all platforms because Python
    treats ``.env`` as a stem with no extension. We detect this case by
    checking if the name starts with a dot and has no further dot in the name.

        Path(".env")        -> ".env"
        Path("config.yaml") -> ".yaml"
        Path("config.ini")  -> ".ini"
    """
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    # Dotfile: name is entirely the "extension" (e.g. ".env", ".envrc")
    name = path.name.lower()
    if name.startswith(".") and "." not in name[1:]:
        return name
    return suffix


def _apply_flat_overrides(
    config: ConfigDict,
    overrides: dict[str, str],
    *,
    case_insensitive: bool = False,
    inject_new: bool = False,
    skip_templates: bool = False,
) -> ConfigDict:
    """Apply flat string overrides to the top level of *config*.

    Parameters
    ----------
    case_insensitive:
        Match override keys to config keys without regard to case.
        The config key casing is preserved in the result.
    inject_new:
        If ``True``, keys present in *overrides* but absent from *config*
        are inserted as new entries. If ``False`` (default), only existing
        keys are updated — unknown override keys are silently ignored.
    skip_templates:
        If ``True``, skip overriding any config value that contains a
        ``${...}`` template token — those values are left for interpolation
        to expand instead. Without this guard, the override step would
        clobber ``"${LOG_DIR}/app"`` with ``"/var/log"`` before interpolation
        runs, losing the ``/app`` suffix permanently.
    """
    import re
    _TEMPLATE_RE = re.compile(r"\$\{[^}]+\}")

    def _has_template(value: Any) -> bool:
        return isinstance(value, str) and bool(_TEMPLATE_RE.search(value))

    result = dict(config)

    if case_insensitive:
        lower_map = {k.lower(): k for k in result}
        for override_key, value in overrides.items():
            original_key = lower_map.get(override_key.lower())
            if original_key is not None:
                if skip_templates and _has_template(result[original_key]):
                    continue   # leave template intact for interpolation
                result[original_key] = value
            elif inject_new:
                result[override_key] = value
    else:
        for key, value in overrides.items():
            if key in result:
                if skip_templates and _has_template(result[key]):
                    continue   # leave template intact for interpolation
                result[key] = value
            elif inject_new:
                result[key] = value

    return result


def _interpolate_dict(config: ConfigDict, env_vars: dict[str, str]) -> ConfigDict:
    """Recursively expand ``${KEY}`` references in all string values.

    Traverses nested dicts. Non-string values are left untouched.
    Unknown ``${KEY}`` references are left as-is.

    Parameters
    ----------
    config:
        The config dict to expand (not mutated — a new dict is returned).
    env_vars:
        Flat dict of available variable values. Typically a merge of
        dotenv values and/or os.environ.
    """
    result: ConfigDict = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = _interpolate_dict(value, env_vars)
        elif isinstance(value, str):
            result[key] = _expand_vars(value, env_vars)
        else:
            result[key] = value
    return result


def _expand_vars(value: str, env_vars: dict[str, str]) -> str:
    """Replace all ``${KEY}`` tokens in *value* with values from *env_vars*.

    Handles:
        ${KEY}          standard token
        ${KEY:-default} token with fallback if KEY is missing or empty

    Unknown tokens with no default are left as-is so callers can detect them.

    Examples
    --------
    >>> _expand_vars("postgres://${HOST}/db", {"HOST": "localhost"})
    'postgres://localhost/db'
    >>> _expand_vars("${MISSING}", {})
    '${MISSING}'
    >>> _expand_vars("${TIMEOUT:-30}", {})
    '30'
    >>> _expand_vars("${PORT:-8080}", {"PORT": "9090"})
    '9090'
    """
    import re

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        default = match.group(2)   # None if no :- syntax

        resolved = env_vars.get(key)

        if resolved:
            return resolved
        if default is not None:
            return default
        # Unknown reference — leave the original token intact
        return match.group(0)

    # Match ${KEY} and ${KEY:-default}
    pattern = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")
    return pattern.sub(_replace, value)