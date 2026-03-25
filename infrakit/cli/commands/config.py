"""
infrakit.cli.commands.config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``infrakit config`` subcommand group.

Commands
--------
    infrakit config convert  <src> <target> [--overwrite] [--quiet]
    infrakit config export   <src> [target] --format FORMAT [--overwrite]
                             target is optional — omit to print to stdout
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import typer

from infrakit.core.config.converter import convert_file, ConversionWarning
from infrakit.core.config.exporter import export_file, export_dict
from infrakit.core.config.loader import load

config_app = typer.Typer(
    name="config",
    help="Convert and export configuration files.",
    no_args_is_help=True,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _abort(msg: str) -> None:
    typer.echo(typer.style(f"✗  {msg}", fg=typer.colors.RED), err=True)
    raise typer.Exit(1)


def _ok(msg: str) -> None:
    typer.echo(typer.style(f"✓  {msg}", fg=typer.colors.GREEN))


def _info(msg: str) -> None:
    typer.echo(typer.style(f"   {msg}", fg=typer.colors.BRIGHT_BLACK))


def _warn(msg: str) -> None:
    typer.echo(typer.style(f"⚠  {msg}", fg=typer.colors.YELLOW), err=True)


# ── infrakit config convert ───────────────────────────────────────────────────

@config_app.command("convert")
def cmd_convert(
    src: Path = typer.Argument(..., help="Source config file."),
    target: Path = typer.Argument(..., help="Target config file (format inferred from extension)."),
    overwrite: bool = typer.Option(False, "--overwrite", "-y", help="Overwrite target if it already exists."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress lossy-conversion warnings."),
) -> None:
    """
    Convert a config file from one format to another.

    Format is inferred from the file extension.
    Supported: json, yaml, ini, env.

    \b
    Examples
    --------
      ik config convert config.yaml config.json
      ik config convert settings.ini settings.yaml --overwrite
      ik config convert config.json .env -y
    """
    if not src.exists():
        _abort(f"Source file not found: {src}")

    if target.exists() and not overwrite:
        _abort(f"Target already exists: {target}  (pass --overwrite / -y to replace)")

    caught: list = []

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", ConversionWarning)
        try:
            convert_file(src, target, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001
            _abort(f"Conversion failed: {exc}")
        caught = [x.message for x in w if issubclass(x.category, ConversionWarning)]

    if caught and not quiet:
        for cw in caught:
            _warn(f"Lossy conversion — key '{cw.key}': {cw.reason}")  # type: ignore[attr-defined]

    _ok(f"Converted  {src}  →  {target}")


# ── infrakit config export ────────────────────────────────────────────────────

_VALID_FORMATS = {"json", "yaml", "ini", "env"}


@config_app.command("export")
def cmd_export(
    src: Path = typer.Argument(..., help="Source config file to sanitize."),
    target: Optional[Path] = typer.Argument(None, help="Output file. Omit to print the template to stdout."),
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json | yaml | ini | env."),
    overwrite: bool = typer.Option(False, "--overwrite", "-y", help="Overwrite target if it already exists. Ignored when printing to stdout."),
) -> None:
    """
    Export a sanitized config template — all values become YOUR_VALUE_HERE.

    When no target file is given the template is printed to stdout, which is
    useful for quick inspection or piping into another tool.

    \b
    Examples
    --------
      ik config export .env -f env                          # print to terminal
      ik config export .env template.env -f env             # write to file
      ik config export config.yaml config.template.yaml -f yaml
      ik config export secrets.json safe.json -f json -y
    """
    if not src.exists():
        _abort(f"Source file not found: {src}")

    if fmt not in _VALID_FORMATS:
        _abort(f"Unknown format '{fmt}'. Choose from: {', '.join(sorted(_VALID_FORMATS))}")

    # ── stdout mode ───────────────────────────────────────────────────────────
    if target is None:
        try:
            data = load(src, cast_values=False)
            output = export_dict(data, to_format=fmt)
        except Exception as exc:  # noqa: BLE001
            _abort(f"Export failed: {exc}")
            return
        typer.echo(output)
        return

    # ── file mode ─────────────────────────────────────────────────────────────
    if target.exists() and not overwrite:
        _abort(f"Target already exists: {target}  (pass --overwrite / -y to replace)")

    try:
        export_file(src, target, to_format=fmt, overwrite=overwrite)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Export failed: {exc}")
        return

    _ok(f"Exported sanitized template  {src}  →  {target}  (format: {fmt})")
    _info("All values have been replaced with YOUR_VALUE_HERE.")