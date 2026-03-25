"""
infrakit.core.config.exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Export a config file or dict with all values replaced by YOUR_VALUE_HERE —
safe to share without leaking real credentials.

The output format is always an explicit input — nothing is inferred.

Output style:
    DATABASE_URL=YOUR_VALUE_HERE
    PORT=YOUR_VALUE_HERE
    DEBUG=YOUR_VALUE_HERE

Usage:
    from infrakit.core.config.exporter import export_file, export_dict, export_string

    # File -> sanitized file, choose output format explicitly
    export_file("config.yaml", ".env.example", to_format="env")
    export_file(".env", "config.example.yaml", to_format="yaml")

    # Dict -> sanitized string
    result = export_dict({"PORT": 8080, "DEBUG": True}, to_format="env")
    print(result)

    # Raw string -> sanitized string
    result = export_string(raw_env_text, from_format="env", to_format="ini")
"""

from __future__ import annotations

import json
from configparser import ConfigParser
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

PLACEHOLDER = "YOUR_VALUE_HERE"

_EXT_TO_FORMAT: dict[str, Format] = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".ini":  "ini",
    ".cfg":  "ini",
    ".env":  "env",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_file(
    source: str | Path,
    target: str | Path,
    *,
    to_format: Format,
    overwrite: bool = False,
) -> None:
    """Read *source*, replace all values with YOUR_VALUE_HERE, write to *target*.

    Parameters
    ----------
    source:
        Path to the real config file (e.g. ``.env``, ``config.yaml``).
    target:
        Path to write the sanitized output (e.g. ``.env.example``).
    to_format:
        Output format — one of ``"env"``, ``"ini"``, ``"json"``, ``"yaml"``.
        Always required; never inferred from the filename.
    overwrite:
        If False (default), raises :exc:`FileExistsError` when *target* exists.

    Raises
    ------
    FileNotFoundError
        If *source* does not exist.
    FileExistsError
        If *target* exists and *overwrite* is False.
    ValueError
        If *to_format* is not a supported format.
    """
    source = Path(source)
    target = Path(target)

    if not source.exists():
        raise FileNotFoundError(f"Source config not found: '{source}'")
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"Target '{target}' already exists. Pass overwrite=True to replace."
        )

    _validate_format(to_format)
    from_fmt = _infer_format(source)

    raw = source.read_text(encoding="utf-8")
    data = _parse(raw, from_fmt)
    output = export_dict(data, to_format=to_format)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")


def export_string(
    raw: str,
    *,
    from_format: Format,
    to_format: Format,
) -> str:
    """Parse *raw* as *from_format*, sanitize all values, return as *to_format*.

    Parameters
    ----------
    raw:
        The raw config string to sanitize.
    from_format:
        Format of *raw* — one of ``"env"``, ``"ini"``, ``"json"``, ``"yaml"``.
    to_format:
        Desired output format — one of ``"env"``, ``"ini"``, ``"json"``, ``"yaml"``.

    Returns
    -------
    str
        Sanitized config string in *to_format*.
    """
    _validate_format(from_format)
    _validate_format(to_format)
    data = _parse(raw, from_format)
    return export_dict(data, to_format=to_format)


def export_dict(data: ConfigDict, *, to_format: Format) -> str:
    """Sanitize *data* and serialize to *to_format*.

    All values — at every nesting level — are replaced with YOUR_VALUE_HERE.
    Keys and structure are preserved exactly.

    Parameters
    ----------
    data:
        A config dict, as returned by the loader.
    to_format:
        Output format — one of ``"env"``, ``"ini"``, ``"json"``, ``"yaml"``.

    Returns
    -------
    str
        The sanitized, serialized config string.

    Raises
    ------
    ValueError
        If *to_format* is not supported.
    """
    _validate_format(to_format)
    if to_format == "env":
        return _export_as_env(data)
    if to_format == "ini":
        return _export_as_ini(data)
    if to_format == "json":
        return _export_as_json(data)
    if to_format == "yaml":
        return _export_as_yaml(data)


# ---------------------------------------------------------------------------
# Format serializers
# ---------------------------------------------------------------------------

def _export_as_env(data: ConfigDict) -> str:
    lines: list[str] = []

    def _add(key: str) -> None:
        lines.append(f"{key}={PLACEHOLDER}")

    for k, v in data.items():
        if isinstance(v, dict):
            lines.append(f"\n# [{k}]")
            for nested_k in v:
                _add(f"{k.upper()}__{nested_k.upper()}")
        else:
            _add(k)

    return "\n".join(lines) + "\n"


def _export_as_ini(data: ConfigDict) -> str:
    lines: list[str] = []

    for k, v in data.items():
        if isinstance(v, dict):
            lines.append(f"[{k}]")
            for nested_k in v:
                lines.append(f"{nested_k} = {PLACEHOLDER}")
            lines.append("")
        else:
            lines.append(f"{k} = {PLACEHOLDER}")

    return "\n".join(lines).rstrip() + "\n"


def _export_as_json(data: ConfigDict) -> str:
    return json.dumps(_sanitize_dict(data), indent=2) + "\n"


def _export_as_yaml(data: ConfigDict) -> str:
    if not _YAML_AVAILABLE:
        raise ValueError("PyYAML is required for YAML export. pip install pyyaml")
    header = "# generated by infrakit exporter — safe to share\n"
    return header + yaml.dump(
        _sanitize_dict(data),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _sanitize_dict(data: ConfigDict) -> ConfigDict:
    """Recursively replace every leaf value with PLACEHOLDER."""
    result: ConfigDict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        else:
            result[k] = PLACEHOLDER
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_format(fmt: Format) -> None:
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. "
            f"Choose one of: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )


def _infer_format(path: Path) -> Format:
    """Infer format from file extension, handling dotfiles like .env."""
    suffix = path.suffix.lower()
    if not suffix:
        name = path.name.lower()
        if name.startswith(".") and "." not in name[1:]:
            suffix = name
    fmt = _EXT_TO_FORMAT.get(suffix)
    if fmt is None:
        raise ValueError(
            f"Cannot infer format from '{path.name}'. "
            f"Supported extensions: {', '.join(sorted(_EXT_TO_FORMAT))}"
        )
    return fmt


def _parse(raw: str, fmt: Format) -> ConfigDict:
    if fmt == "json":
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    if fmt == "yaml":
        if not _YAML_AVAILABLE:
            raise ValueError("PyYAML required. pip install pyyaml")
        return yaml.safe_load(raw) or {}
    if fmt == "ini":
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
    if fmt == "env":
        result = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
        return result
    raise ValueError(f"Unknown format '{fmt}'")