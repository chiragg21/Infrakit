"""
infrakit.core.config.converter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Convert a config dict (or file) between supported formats.
Lossy conversions (e.g. YAML list → INI) are handled by stringifying the value
and recording a warning — no data is silently dropped.

Usage:
    from infrakit.core.config.converter import convert_file, convert_dict

    # File → file
    warnings = convert_file("config.yaml", "config.ini")

    # Dict → string (useful for previewing output)
    output, warnings = convert_dict(data, from_format="yaml", to_format="ini")

    # Check for lossy conversions
    for w in warnings:
        print(w)
"""

from __future__ import annotations

import json
from configparser import ConfigParser
from io import StringIO
from pathlib import Path
from typing import Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ConfigDict = dict[str, Any]
Format = str   # "json" | "yaml" | "ini" | "env"

SUPPORTED_FORMATS = {"json", "yaml", "ini", "env"}

# Maps file extensions to format names
_EXT_TO_FORMAT: dict[str, Format] = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".ini":  "ini",
    ".cfg":  "ini",
    ".env":  "env",
}

# Maps format names to canonical output extensions
_FORMAT_TO_EXT: dict[Format, str] = {
    "json": ".json",
    "yaml": ".yaml",
    "ini":  ".ini",
    "env":  ".env",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConversionError(Exception):
    """Raised when a conversion cannot be completed."""


# ---------------------------------------------------------------------------
# Conversion warnings
# ---------------------------------------------------------------------------

class ConversionWarning:
    """Records a lossy conversion on a single key.

    Attributes
    ----------
    key:
        The dot-separated config key that was affected.
    original:
        The original Python value.
    stringified:
        The string representation written to the output.
    reason:
        Human-readable explanation of why the conversion was lossy.
    """

    def __init__(
        self,
        key: str,
        original: Any,
        stringified: str,
        reason: str,
    ) -> None:
        self.key = key
        self.original = original
        self.stringified = stringified
        self.reason = reason

    def __str__(self) -> str:
        return (
            f"[{self.key}] Lossy conversion: {self.reason}. "
            f"Value {self.original!r} written as {self.stringified!r}."
        )

    def __repr__(self) -> str:
        return f"ConversionWarning(key={self.key!r}, reason={self.reason!r})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_file(
    source: str | Path,
    target: str | Path,
    *,
    overwrite: bool = False,
) -> list[ConversionWarning]:
    """Convert *source* config file to the format implied by *target*'s extension.

    Parameters
    ----------
    source:
        Path to the input file. Format inferred from extension.
    target:
        Path to the output file. Format inferred from extension.
        The file is created (or overwritten if *overwrite* is True).
    overwrite:
        If False (default), raises :exc:`FileExistsError` when *target* exists.

    Returns
    -------
    list[ConversionWarning]
        Any lossy conversions that occurred. Empty if conversion was lossless.

    Raises
    ------
    FileNotFoundError
        If *source* does not exist.
    FileExistsError
        If *target* exists and *overwrite* is False.
    ConversionError
        If the format combination is not supported.
    """
    source = Path(source)
    target = Path(target)

    if not source.exists():
        raise FileNotFoundError(f"Source file not found: '{source}'")

    if target.exists() and not overwrite:
        raise FileExistsError(
            f"Target file '{target}' already exists. Pass overwrite=True to replace it."
        )

    from_fmt = _infer_format(source)
    to_fmt   = _infer_format(target)

    raw = source.read_text(encoding="utf-8")
    data = _parse(raw, from_fmt)
    output, warnings = _serialize(data, to_fmt, source_format=from_fmt)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")

    return warnings


def convert_dict(
    data: ConfigDict,
    *,
    from_format: Format,
    to_format: Format,
) -> tuple[str, list[ConversionWarning]]:
    """Convert *data* from one format to another, returning the serialized string.

    Parameters
    ----------
    data:
        A config dict (as returned by the loader).
    from_format:
        The logical origin format of *data* — used to decide which lossy
        conversion rules apply (e.g. INI sections vs flat keys).
    to_format:
        The desired output format.

    Returns
    -------
    tuple[str, list[ConversionWarning]]
        ``(serialized_string, warnings)``
    """
    if from_format not in SUPPORTED_FORMATS:
        raise ConversionError(
            f"Unknown source format '{from_format}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    if to_format not in SUPPORTED_FORMATS:
        raise ConversionError(
            f"Unknown target format '{to_format}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    return _serialize(data, to_format, source_format=from_format)


# ---------------------------------------------------------------------------
# Format parsers  (string → dict)
# ---------------------------------------------------------------------------

def _parse(raw: str, fmt: Format) -> ConfigDict:
    if fmt == "json":
        return _parse_json(raw)
    if fmt == "yaml":
        return _parse_yaml(raw)
    if fmt == "ini":
        return _parse_ini(raw)
    if fmt == "env":
        return _parse_env(raw)
    raise ConversionError(f"No parser for format '{fmt}'")


def _parse_json(raw: str) -> ConfigDict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConversionError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConversionError("JSON root must be an object.")
    return data


def _parse_yaml(raw: str) -> ConfigDict:
    if not _YAML_AVAILABLE:
        raise ConversionError(
            "PyYAML is required for YAML conversion. pip install pyyaml"
        )
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConversionError(f"Invalid YAML: {exc}") from exc
    return data or {}


def _parse_ini(raw: str) -> ConfigDict:
    parser = ConfigParser()
    parser.read_string(raw)
    result: ConfigDict = {}
    if parser.defaults():
        result["DEFAULT"] = dict(parser.defaults())
    for section in parser.sections():
        result[section] = {
            k: parser.get(section, k)
            for k in parser.options(section)
            if k not in parser.defaults()
        }
    return result


def _parse_env(raw: str) -> ConfigDict:
    result: ConfigDict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


# ---------------------------------------------------------------------------
# Format serializers  (dict → string)
# ---------------------------------------------------------------------------

def _serialize(
    data: ConfigDict,
    fmt: Format,
    *,
    source_format: Format,
) -> tuple[str, list[ConversionWarning]]:
    if fmt == "json":
        return _serialize_json(data)
    if fmt == "yaml":
        return _serialize_yaml(data)
    if fmt == "ini":
        return _serialize_ini(data, source_format=source_format)
    if fmt == "env":
        return _serialize_env(data, source_format=source_format)
    raise ConversionError(f"No serializer for format '{fmt}'")


def _serialize_json(data: ConfigDict) -> tuple[str, list[ConversionWarning]]:
    """JSON supports all Python types natively — never lossy."""
    return json.dumps(data, indent=2, default=str) + "\n", []


def _serialize_yaml(data: ConfigDict) -> tuple[str, list[ConversionWarning]]:
    if not _YAML_AVAILABLE:
        raise ConversionError(
            "PyYAML is required for YAML serialization. pip install pyyaml"
        )
    output = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return output, []


def _serialize_ini(
    data: ConfigDict,
    *,
    source_format: Format,
) -> tuple[str, list[ConversionWarning]]:
    """Serialize to INI format.

    INI limitations:
    - All values are strings
    - No native list, bool, int, float, or null types
    - Keys must live inside a [section] — top-level flat keys go into [DEFAULT]

    Lossy conversions are stringified and recorded as warnings.
    """
    warnings: list[ConversionWarning] = []
    parser = ConfigParser()

    def _add_section(section: str, mapping: dict[str, Any]) -> None:
        parser.add_section(section)
        for k, v in mapping.items():
            str_v, warn = _to_ini_string(f"{section}.{k}", v)
            if warn:
                warnings.append(warn)
            parser.set(section, k, str_v)

    # If source was already INI-shaped (nested dicts = sections), preserve that.
    # Otherwise, flatten everything into a single [config] section.
    has_sections = source_format in {"ini"} or all(
        isinstance(v, dict) for v in data.values()
    )

    if has_sections:
        for section, value in data.items():
            if isinstance(value, dict):
                _add_section(section, value)
            else:
                # Top-level scalar — goes into DEFAULT
                if not parser.has_section("DEFAULT"):
                    pass  # ConfigParser DEFAULT is implicit
                str_v, warn = _to_ini_string(section, value)
                if warn:
                    warnings.append(warn)
                parser.defaults()[section] = str_v
    else:
        _add_section("config", data)

    buf = StringIO()
    parser.write(buf)
    return buf.getvalue(), warnings


def _serialize_env(
    data: ConfigDict,
    *,
    source_format: Format,
) -> tuple[str, list[ConversionWarning]]:
    """.env format: KEY=value, flat, all strings. No sections."""
    warnings: list[ConversionWarning] = []
    lines: list[str] = []

    def _add(original_key: str, output_key: str, value: Any) -> None:
        # original_key used in warnings (preserves source casing)
        # output_key used in the actual .env line (uppercased for non-env sources)
        str_v, warn = _to_env_string(original_key, value)
        if warn:
            warnings.append(warn)
        lines.append(f"{output_key}={str_v}")

    for k, v in data.items():
        if isinstance(v, dict):
            # Flatten nested dicts: {"db": {"host": "x"}} → DB__HOST=x
            for nested_k, nested_v in v.items():
                flat_key = f"{k.upper()}__{nested_k.upper()}"
                original = f"{k}__{nested_k}"
                _add(original, flat_key, nested_v)
        else:
            out_key = k if source_format == "env" else k.upper()
            _add(k, out_key, v)

    return "\n".join(lines) + "\n", warnings


# ---------------------------------------------------------------------------
# Value stringification helpers
# ---------------------------------------------------------------------------

def _to_ini_string(key: str, value: Any) -> tuple[str, ConversionWarning | None]:
    """Convert *value* to an INI-safe string, recording a warning if lossy."""
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return str(value).lower(), None   # true/false — readable
    if isinstance(value, (int, float)):
        return str(value), None
    if value is None:
        return "", None

    # Lists, dicts, and anything else → stringify + warn
    stringified = _stringify_complex(value)
    return stringified, ConversionWarning(
        key=key,
        original=value,
        stringified=stringified,
        reason=f"INI format does not support {type(value).__name__} values",
    )


def _to_env_string(key: str, value: Any) -> tuple[str, ConversionWarning | None]:
    """.env values are always strings — same lossy rules as INI."""
    if isinstance(value, str):
        # Quote values with spaces
        return f'"{value}"' if " " in value else value, None
    if isinstance(value, bool):
        return str(value).lower(), None
    if isinstance(value, (int, float)):
        return str(value), None
    if value is None:
        return "", None

    stringified = _stringify_complex(value)
    return stringified, ConversionWarning(
        key=key,
        original=value,
        stringified=stringified,
        reason=f".env format does not support {type(value).__name__} values",
    )


def _stringify_complex(value: Any) -> str:
    """Stringify a complex value (list, dict, etc.) into a compact string.

    Lists  → comma-joined:  [1, "a", True]  → "1,a,true"
    Dicts  → JSON inline:   {"a": 1}        → '{"a": 1}'
    Other  → repr fallback
    """
    if isinstance(value, list):
        return ",".join(_scalar_str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    return repr(value)


def _scalar_str(value: Any) -> str:
    """Compact string representation of a scalar for use inside lists."""
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_format(path: Path) -> Format:
    """Infer format from file extension, handling dotfiles like .env."""
    suffix = path.suffix.lower()
    if not suffix:
        # Dotfile: .env, .envrc, etc.
        name = path.name.lower()
        if name.startswith(".") and "." not in name[1:]:
            suffix = name
    fmt = _EXT_TO_FORMAT.get(suffix)
    if fmt is None:
        raise ConversionError(
            f"Cannot infer format from extension '{suffix}'. "
            f"Supported extensions: {', '.join(sorted(_EXT_TO_FORMAT))}"
        )
    return fmt