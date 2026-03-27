"""
infrakit/cli/commands/deps.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Typer-based CLI commands for dependency management.

Register in your main CLI app:

    from infrakit.cli.commands.deps import app as deps_app
    main_app.add_typer(deps_app, name="deps")

Commands:
    ik deps export     — write a file of only the deps actually used
    ik deps check      — health check: outdated / vulns / licenses
    ik deps clean      — remove unused packages from venv
    ik deps optimize   — sort, deduplicate, and clean imports
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

deps_app = typer.Typer(
    name="deps",
    help="Dependency management — scan, export, check, clean, optimise.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)


# ---------------------------------------------------------------------------
# Shared display helpers
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    typer.echo()
    typer.echo(typer.style(f"  ── {title}", fg=typer.colors.BRIGHT_WHITE, bold=True))
    typer.echo(typer.style("  " + "─" * (len(title) + 5), fg=typer.colors.BRIGHT_BLACK))


def _ok(msg: str) -> None:
    typer.echo(typer.style("  ✓ ", fg=typer.colors.GREEN) + msg)


def _warn(msg: str) -> None:
    typer.echo(typer.style("  ⚠ ", fg=typer.colors.YELLOW) + msg)


def _err(msg: str) -> None:
    typer.echo(typer.style("  ✗ ", fg=typer.colors.RED) + msg)


def _info(msg: str) -> None:
    typer.echo(typer.style("  · ", fg=typer.colors.BRIGHT_BLACK) + msg)


def _header(cmd: str) -> None:
    typer.echo()
    typer.echo(typer.style(f"  infrakit deps {cmd}", fg=typer.colors.GREEN, bold=True))


def _progress(label: str) -> None:
    typer.echo(typer.style(f"  {label}…", fg=typer.colors.BRIGHT_BLACK))


# ---------------------------------------------------------------------------
# ik deps export
# ---------------------------------------------------------------------------

@deps_app.command("export")
def deps_export(
    root: Annotated[Path, typer.Option("--root", "-r", help="Project root directory to scan.")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Path for new requirements file.")] = None,
    inplace: Annotated[bool, typer.Option("--inplace", "-i", help="Update existing requirements.txt / pyproject.toml in-place.")] = False,
    no_versions: Annotated[bool, typer.Option("--no-versions", help="Omit version specifiers from output.")] = False,
    notebooks: Annotated[bool, typer.Option("--notebooks", "-n", help="Also scan Jupyter notebooks (.ipynb).")] = False,
    no_gitignore: Annotated[bool, typer.Option("--no-gitignore", help="Disable .gitignore filtering.")] = False,
):
    """
    Scan the project and export **only** the dependencies that are actually used.

    Possibly-unused imports (imported but name never referenced) are printed
    to stdout for your review but are **not** written to the output file.

    **Examples**

        ik deps export -o requirements.used.txt

        ik deps export --inplace

        ik deps export -o deps.txt --notebooks
    """
    from infrakit.deps import export as _export

    root_path = root.resolve()

    if not inplace and output is None:
        _err("Provide --output <path> or use --inplace.")
        _info("Example: ik deps export -o requirements.used.txt")
        raise typer.Exit(1)

    _header("export")
    typer.echo(typer.style(f"  root: {root_path}", fg=typer.colors.BRIGHT_BLACK))
    typer.echo()

    _progress("Scanning files")
    scan_result, dep_files = _export(
        root=root_path,
        output=output,
        inplace=inplace,
        keep_versions=not no_versions,
        include_notebooks=notebooks,
        use_gitignore=not no_gitignore,
    )

    # ── Scan summary ──────────────────────────────────────────────────────
    _section("Scan results")
    typer.echo(f"    Files scanned:   {typer.style(str(len(scan_result.files)), fg=typer.colors.CYAN)}")
    typer.echo(f"    Used packages:   {typer.style(str(len(scan_result.used_packages)), fg=typer.colors.GREEN)}")
    typer.echo(f"    Dep files found: {typer.style(str(len(dep_files)), fg=typer.colors.CYAN)}")

    if scan_result.errors:
        _section("Parse errors")
        for path, err in scan_result.errors:
            _warn(f"{path.name}: {err}")

    # ── Used packages ─────────────────────────────────────────────────────
    _section("Used packages")
    for pkg in sorted(scan_result.used_packages, key=str.lower):
        fc = len(scan_result.used_packages[pkg])
        plural = "s" if fc != 1 else ""
        typer.echo(
            f"    {typer.style(pkg, fg=typer.colors.GREEN)}"
            f"  {typer.style(f'{fc} file{plural}', fg=typer.colors.BRIGHT_BLACK)}"
        )

    # ── Possibly unused ───────────────────────────────────────────────────
    if scan_result.possibly_unused:
        _section("Possibly unused imports  (not written to output)")
        typer.echo(typer.style(
            "    These packages are imported but their names were\n"
            "    never referenced in code. Review before removing.\n",
            fg=typer.colors.BRIGHT_BLACK,
        ))
        for pkg, files in sorted(scan_result.possibly_unused.items()):
            sample = ", ".join(f.name for f in sorted(files)[:3])
            suffix = " …" if len(files) > 3 else ""
            typer.echo(
                f"    {typer.style(pkg, fg=typer.colors.YELLOW)}"
                f"  {typer.style(f'in: {sample}{suffix}', fg=typer.colors.BRIGHT_BLACK)}"
            )

    # ── Unknown pip names ─────────────────────────────────────────────────
    if scan_result.unknown_imports:
        _section("Unknown package names")
        typer.echo(typer.style(
            "    Could not match to a known pip package name.\n"
            "    May be a local module or a package with a non-standard name.\n",
            fg=typer.colors.BRIGHT_BLACK,
        ))
        for pkg in sorted(scan_result.unknown_imports):
            _warn(f"{pkg} — verify this is not a pip package")

    # ── Output ────────────────────────────────────────────────────────────
    _section("Output")
    if inplace:
        for df in dep_files:
            _ok(f"Updated in-place: {df.path}")
    elif output:
        _ok(f"Written to: {output.resolve()}")

    typer.echo()


# ---------------------------------------------------------------------------
# ik deps check
# ---------------------------------------------------------------------------

@deps_app.command("check")
def deps_check(
    root: Annotated[Path, typer.Option("--root", "-r", help="Project root (scanned for used packages if --packages not given).")] = Path("."),
    packages: Annotated[Optional[list[str]], typer.Option("--package", "-p", help="Specific package to check. Repeat for multiple.")] = None,
    outdated: Annotated[bool, typer.Option("--outdated/--no-outdated", help="Check for outdated packages via PyPI.")] = True,
    security: Annotated[bool, typer.Option("--security/--no-security", help="Scan for known vulnerabilities via pip-audit.")] = True,
    licenses: Annotated[bool, typer.Option("--licenses/--no-licenses", help="Report license information.")] = True,
    notebooks: Annotated[bool, typer.Option("--notebooks", "-n", help="Also scan Jupyter notebooks.")] = False,
):
    """
    Health check your dependencies.

    All three checks are **enabled by default** — toggle with flags.

    **Examples**

        ik deps check

        ik deps check --no-security

        ik deps check -p requests -p numpy
    """
    from infrakit.deps import scan as _scan, check as _check

    root_path = root.resolve()
    _header("check")

    pkg_list: list[str]
    if packages:
        pkg_list = list(packages)
        typer.echo(typer.style(f"  Checking {len(pkg_list)} specified package(s).", fg=typer.colors.BRIGHT_BLACK))
    else:
        typer.echo(typer.style(f"  root: {root_path}", fg=typer.colors.BRIGHT_BLACK))
        _progress("Scanning project for used packages")
        result = _scan(root_path, include_notebooks=notebooks)
        pkg_list = list(result.used_packages.keys())
        typer.echo(typer.style(f"  Found {len(pkg_list)} packages.", fg=typer.colors.BRIGHT_BLACK))

    if not pkg_list:
        _warn("No packages found to check.")
        return

    _progress("Running checks")
    report = _check(packages=pkg_list, outdated=outdated, security=security, licenses=licenses)

    # ── Outdated ──────────────────────────────────────────────────────────
    if outdated and report.outdated:
        _section("Outdated packages")
        n_out = sum(1 for p in report.outdated if p.status == "outdated")
        n_up = sum(1 for p in report.outdated if p.status == "up-to-date")

        if n_out == 0:
            _ok(f"All {n_up} packages are up-to-date.")
        else:
            typer.echo(
                f"    {typer.style(str(n_out), fg=typer.colors.YELLOW)} outdated, "
                f"{typer.style(str(n_up), fg=typer.colors.GREEN)} up-to-date"
            )

        typer.echo()
        col = max((len(p.name) for p in report.outdated), default=10) + 2
        typer.echo(typer.style(
            f"    {'Package':<{col}} {'Installed':<14} {'Latest':<14} Status",
            fg=typer.colors.BRIGHT_BLACK,
        ))
        typer.echo(typer.style("    " + "─" * (col + 46), fg=typer.colors.BRIGHT_BLACK))

        for p in report.outdated:
            if p.status == "outdated":
                s = typer.style("● outdated", fg=typer.colors.YELLOW)
            elif p.status == "up-to-date":
                s = typer.style("✓ up-to-date", fg=typer.colors.GREEN)
            elif p.status == "not-installed":
                s = typer.style("○ not installed", fg=typer.colors.BRIGHT_BLACK)
            else:
                s = typer.style(f"? {p.status}", fg=typer.colors.BRIGHT_BLACK)

            typer.echo(
                f"    {p.name:<{col}}"
                f"{typer.style(p.current, fg=typer.colors.BRIGHT_WHITE):<14}"
                f"{typer.style(p.latest, fg=typer.colors.CYAN):<14}"
                f"{s}"
            )

    # ── Security ──────────────────────────────────────────────────────────
    if security:
        _section("Security vulnerabilities")
        sec_err = next((e for e in report.errors if "Security scan" in e), None)
        if sec_err:
            _warn(sec_err.replace("Security scan: ", ""))
        elif not report.vulnerabilities:
            _ok("No known vulnerabilities found.")
        else:
            _err(f"{len(report.vulnerabilities)} vulnerability/ies found!")
            typer.echo()
            for v in report.vulnerabilities:
                typer.echo(
                    f"    {typer.style(v.vuln_id, fg=typer.colors.RED, bold=True)}  "
                    f"{typer.style(v.package, fg=typer.colors.BRIGHT_WHITE)} {v.installed_version}"
                )
                typer.echo(f"      Fix:  {typer.style(v.fix_version, fg=typer.colors.YELLOW)}")
                desc = v.description[:97] + "…" if len(v.description) > 100 else v.description
                typer.echo(f"      Desc: {typer.style(desc, fg=typer.colors.BRIGHT_BLACK)}")
                typer.echo()

    # ── Licenses ──────────────────────────────────────────────────────────
    if licenses and report.licenses:
        _section("Licenses")
        col = max((len(l.package) for l in report.licenses), default=10) + 2
        lw = max((len(l.license) for l in report.licenses), default=10) + 2
        typer.echo(typer.style(
            f"    {'Package':<{col}} {'License':<{lw}} Notes",
            fg=typer.colors.BRIGHT_BLACK,
        ))
        typer.echo(typer.style("    " + "─" * (col + lw + 30), fg=typer.colors.BRIGHT_BLACK))

        for lic in report.licenses:
            if lic.compatible is True:
                ind = typer.style("✓", fg=typer.colors.GREEN)
            elif lic.compatible is False:
                ind = typer.style("✗", fg=typer.colors.RED)
            else:
                ind = typer.style("?", fg=typer.colors.YELLOW)

            typer.echo(
                f"    {lic.package:<{col}}{lic.license:<{lw}}"
                f"{ind} {typer.style(lic.notes, fg=typer.colors.BRIGHT_BLACK)}"
            )

    # ── Other errors ──────────────────────────────────────────────────────
    other = [e for e in report.errors if "Security scan" not in e]
    if other:
        _section("Errors")
        for e in other:
            _err(e)

    typer.echo()


# ---------------------------------------------------------------------------
# ik deps clean
# ---------------------------------------------------------------------------

@deps_app.command("clean")
def deps_clean(
    root: Annotated[Path, typer.Option("--root", "-r", help="Project root directory to scan.")] = Path("."),
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Preview without uninstalling.")] = True,
    keep: Annotated[Optional[list[str]], typer.Option("--keep", "-k", help="Package(s) to protect from removal.")] = None,
    notebooks: Annotated[bool, typer.Option("--notebooks", "-n", help="Also scan notebooks when computing used packages.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
):
    """
    Remove unused packages from the virtual environment.

    Does **not** touch your requirements file — use `ik deps export` for that.
    Dry-run is the default; pass `--no-dry-run` to actually uninstall.

    **Examples**

        ik deps clean                       # dry-run preview

        ik deps clean --no-dry-run          # actually uninstall

        ik deps clean --no-dry-run -k boto3 # keep boto3 even if unused
    """
    from infrakit.deps import clean as _clean

    root_path = root.resolve()
    _header("clean")

    if dry_run:
        typer.echo(typer.style(
            "  mode: dry-run  (pass --no-dry-run to actually remove)",
            fg=typer.colors.YELLOW,
        ))
    else:
        typer.echo(typer.style(
            "  mode: LIVE — packages will be uninstalled",
            fg=typer.colors.RED, bold=True,
        ))
    typer.echo(typer.style(f"  root: {root_path}", fg=typer.colors.BRIGHT_BLACK))
    typer.echo()

    _progress("Scanning project")
    preview = _clean(root=root_path, protected=set(keep or []), dry_run=True)

    if not preview.to_remove:
        _ok("Nothing to remove — your environment is clean.")
        typer.echo()
        return

    _section("Packages to remove")
    for pkg in preview.to_remove:
        typer.echo(f"    {typer.style('−', fg=typer.colors.RED)} {pkg}")

    typer.echo()
    typer.echo(typer.style(
        f"  {len(preview.to_remove)} package(s) would be removed.",
        fg=typer.colors.YELLOW,
    ))

    if dry_run:
        typer.echo()
        _info("Run with --no-dry-run to actually uninstall.")
        typer.echo()
        return

    if not yes:
        typer.echo()
        confirmed = typer.confirm(
            typer.style("  Proceed with uninstall?", fg=typer.colors.YELLOW),
            default=False,
        )
        if not confirmed:
            _info("Aborted.")
            typer.echo()
            return

    typer.echo()
    _progress("Uninstalling")
    live = _clean(root=root_path, protected=set(keep or []), dry_run=False)

    _section("Results")
    for pkg in live.removed:
        _ok(f"Removed: {pkg}")
    for pkg in live.skipped:
        _warn(f"Skipped: {pkg}")
    for e in live.errors:
        _err(e)

    color = typer.colors.GREEN if not live.errors else typer.colors.YELLOW
    typer.echo()
    typer.echo(typer.style(
        f"  Removed {len(live.removed)} / {len(preview.to_remove)} packages.",
        fg=color,
    ))
    typer.echo()


# ---------------------------------------------------------------------------
# ik deps optimize
# ---------------------------------------------------------------------------

@deps_app.command("optimize")
def deps_optimize(
    root: Annotated[Path, typer.Option("--root", "-r", help="Project root directory.")] = Path("."),
    files: Annotated[Optional[list[Path]], typer.Option("--file", "-f", help="Specific file(s) to optimise.")] = None,
    convert: Annotated[Optional[str], typer.Option("--convert", "-c", help="Convert imports: 'absolute' or 'relative'.")] = None,
    no_isort: Annotated[bool, typer.Option("--no-isort", help="Disable isort backend, use built-in sorter.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-d", help="Show changes without writing files.")] = False,
):
    """
    Optimise imports across your project.

    - Sort into groups: stdlib → third-party → local (via isort or built-in)
    - Remove duplicate imports
    - Convert relative ↔ absolute imports (optional)
    - Multi-line formatting for long `from`-imports

    **Examples**

        ik deps optimize

        ik deps optimize --dry-run

        ik deps optimize -f src/main.py

        ik deps optimize --convert absolute
    """
    from infrakit.deps import optimise as _optimise

    if convert and convert not in ("absolute", "relative"):
        _err("--convert must be 'absolute' or 'relative'")
        raise typer.Exit(1)

    root_path = root.resolve()
    file_paths = [f.resolve() for f in files] if files else None

    _header("optimize")
    if dry_run:
        typer.echo(typer.style("  mode: dry-run", fg=typer.colors.YELLOW))
    typer.echo(typer.style(f"  root: {root_path}", fg=typer.colors.BRIGHT_BLACK))
    if convert:
        typer.echo(typer.style(f"  convert: → {convert}", fg=typer.colors.CYAN))
    typer.echo()

    results = _optimise(
        root=root_path,
        files=file_paths,
        convert_to=convert,
        use_isort=not no_isort,
        dry_run=dry_run,
    )

    changed = [r for r in results if r.changed]
    errors  = [r for r in results if r.error]

    if changed:
        label = "Would change" if dry_run else "Changed"
        n_changed = len(changed)
        plural = "s" if n_changed != 1 else ""
        _section(f"{label} ({n_changed} file{plural})")
        for r in changed:
            try:
                rel = r.path.relative_to(root_path)
            except ValueError:
                rel = r.path
            typer.echo(f"    {typer.style(str(rel), fg=typer.colors.CYAN)}")
            for change in r.changes:
                if change.startswith("  "):
                    typer.echo(f"        {typer.style(change.strip(), fg=typer.colors.BRIGHT_BLACK)}")
                else:
                    typer.echo(f"      {typer.style('·', fg=typer.colors.BRIGHT_BLACK)} {change}")
    else:
        _section("No changes needed")
        _ok("All imports are already well-organised.")

    if errors:
        n_errors = len(errors)
        plural = "s" if n_errors != 1 else ""
        _section(f"Errors ({n_errors} file{plural})")
        for r in errors:
            try:
                rel = r.path.relative_to(root_path)
            except ValueError:
                rel = r.path
            _err(f"{rel}: {r.error}")

    _section("Summary")
    typer.echo(f"    Files scanned:  {typer.style(str(len(results)), fg=typer.colors.CYAN)}")
    label = "Would change" if dry_run else "Changed"
    typer.echo(
        f"    {label}:      "
        f"{typer.style(str(len(changed)), fg=typer.colors.GREEN if changed else typer.colors.BRIGHT_BLACK)}"
    )
    typer.echo(
        f"    Errors:         "
        f"{typer.style(str(len(errors)), fg=typer.colors.RED if errors else typer.colors.BRIGHT_BLACK)}"
    )

    if dry_run and changed:
        typer.echo()
        _info("Run without --dry-run to apply changes.")

    typer.echo()