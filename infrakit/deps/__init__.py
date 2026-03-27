"""
infrakit.deps
~~~~~~~~~~~~~
Dependency management module for infrakit.

Public API
----------
scan(root, ...)         → ScanResult
export(root, ...)       → exports used deps to file
check(packages, ...)    → HealthReport
clean(root, ...)        → CleanResult
optimise(root, ...)     → list[OptimizeResult]
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Optional

from infrakit.deps.scanner import ScanResult, scan_project
from infrakit.deps.depfile import (
    DepFile,
    find_dep_files,
    all_declared_packages,
    write_requirements,
    update_requirements_inplace,
    update_pyproject_inplace,
)
from .health import HealthReport, run_health_check
from infrakit.deps.clean import CleanResult, clean_environment
from infrakit.deps.optimizer import OptimizeResult, optimise_project


# ---------------------------------------------------------------------------
# Gitignore integration
# ---------------------------------------------------------------------------

def _build_gitignore_filter(root: Path):
    """
    Returns a callable(rel_posix: str, parts: tuple) → bool that returns
    True when a path should be excluded.

    Tries to reuse infrakit's existing module-tree gitignore logic first;
    falls back to a simple pattern matcher.

    The filter receives:
      rel_posix — forward-slash relative path string, e.g. "ignored/secret.py"
      parts     — tuple of path components, e.g. ("ignored", "secret.py")
    """
    try:
        from infrakit.module.tree import build_gitignore_filter as _ext  # type: ignore

        _inner = _ext(root)

        def _wrapped(rel_posix: str, parts: tuple) -> bool:
            # The existing infrakit filter expects a Path object
            return _inner(root / Path(rel_posix))

        return _wrapped
    except ImportError:
        pass

    # ── Fallback: simple .gitignore parser ────────────────────────────────
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None

    patterns: list[str] = []
    for line in gitignore.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # Strip trailing slash — we'll check directory components directly
            patterns.append(line.rstrip("/"))

    if not patterns:
        return None

    def _filter(rel_posix: str, parts: tuple) -> bool:
        # Check each component of the path against all patterns.
        # This correctly handles "ignored/" matching any directory named "ignored"
        # regardless of OS path separator.
        for pat in patterns:
            # Match against full relative path (forward slashes)
            if fnmatch.fnmatch(rel_posix, pat):
                return True
            # Match against filename
            if parts and fnmatch.fnmatch(parts[-1], pat):
                return True
            # Match against each directory component (handles "ignored/" patterns)
            for part in parts[:-1]:
                if fnmatch.fnmatch(part, pat):
                    return True
        return False

    return _filter


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

def scan(
    root: Path,
    include_notebooks: bool = False,
    use_gitignore: bool = True,
) -> ScanResult:
    """Scan *root* for Python dependencies."""
    gi_filter = _build_gitignore_filter(root) if use_gitignore else None
    return scan_project(root, include_notebooks=include_notebooks, gitignore_filter=gi_filter)


def export(
    root: Path,
    output: Optional[Path] = None,
    inplace: bool = False,
    keep_versions: bool = True,
    include_notebooks: bool = False,
    use_gitignore: bool = True,
) -> tuple[ScanResult, list[DepFile]]:
    """
    Scan project and export only used dependencies.

    Parameters
    ----------
    root:
        Project root directory.
    output:
        Path for new file to write (when inplace=False).
    inplace:
        When True, updates existing dep files in-place.
    keep_versions:
        Preserve version specifiers from existing dep files.
    include_notebooks:
        Also scan .ipynb files.
    use_gitignore:
        Skip files matched by .gitignore.
    """
    result = scan(root, include_notebooks=include_notebooks, use_gitignore=use_gitignore)
    dep_files = find_dep_files(root)
    declared = all_declared_packages(dep_files)

    used_normalised = {
        pkg.lower().replace("_", "-")
        for pkg in result.used_packages
    }

    if inplace:
        for df in dep_files:
            if df.format == "requirements":
                update_requirements_inplace(df, used_normalised)
            elif df.format == "pyproject":
                update_pyproject_inplace(df, used_normalised)
    elif output:
        write_requirements(
            packages=list(result.used_packages.keys()),
            declared=declared,
            output_path=output,
            keep_versions=keep_versions,
        )

    return result, dep_files


def check(
    root: Optional[Path] = None,
    packages: Optional[list[str]] = None,
    outdated: bool = True,
    security: bool = True,
    licenses: bool = True,
) -> HealthReport:
    """
    Run health checks on packages.
    If *packages* is None and *root* is given, scans root first.
    """
    if packages is None:
        if root is None:
            raise ValueError("Provide either root or packages")
        result = scan(root)
        packages = list(result.used_packages.keys())

    return run_health_check(
        packages=packages,
        check_outdated_flag=outdated,
        check_vulns_flag=security,
        check_licenses_flag=licenses,
    )


def clean(
    root: Path,
    protected: Optional[set[str]] = None,
    dry_run: bool = True,
) -> CleanResult:
    """
    Find and optionally remove unused packages from the venv.
    Always dry-run by default — pass dry_run=False to actually uninstall.
    """
    result = scan(root)
    dep_files = find_dep_files(root)
    declared = all_declared_packages(dep_files)

    return clean_environment(
        used_packages=set(result.used_packages.keys()),
        declared_packages={d.name for d in declared.values()},
        protected=protected,
        dry_run=dry_run,
    )


def optimise(
    root: Path,
    files: Optional[list[Path]] = None,
    convert_to: Optional[str] = None,
    use_isort: bool = True,
    dry_run: bool = False,
) -> list[OptimizeResult]:
    """Optimise imports across the project."""
    local_pkgs: set[str] = set()
    for p in root.iterdir():
        if p.is_dir() and (p / "__init__.py").exists():
            local_pkgs.add(p.name)
        if p.is_file() and p.suffix == ".py":
            local_pkgs.add(p.stem)

    return optimise_project(
        root=root,
        files=files,
        local_packages=local_pkgs,
        convert_to=convert_to,
        use_isort=use_isort,
        dry_run=dry_run,
    )


__all__ = [
    "scan", "export", "check", "clean", "optimise",
    "ScanResult", "HealthReport", "CleanResult", "OptimizeResult",
]