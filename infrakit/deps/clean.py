"""
infrakit.deps.clean
~~~~~~~~~~~~~~~~~~~~
Remove unused packages from the active virtual environment.
Never touches dependency files — that is the user's job via `ik deps export`.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

from infrakit.deps.health import get_all_installed


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CleanResult:
    to_remove: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True


# ---------------------------------------------------------------------------
# Protected / never-uninstall packages
# These are pip / setuptools / wheel and infrakit itself.
# ---------------------------------------------------------------------------

_ALWAYS_KEEP: frozenset[str] = frozenset({
    "pip", "setuptools", "wheel", "pkg-resources", "pkg_resources",
    "distribute", "infrakit",
    # Common tools users always want
    "build", "twine", "flit", "hatch", "hatchling", "poetry",
    "pip-tools", "pip_tools",
})


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compute_removable(
    used_packages: set[str],   # pip names actually used in code
    declared_packages: set[str],   # pip names in dep file
    protected: Optional[set[str]] = None,
) -> list[str]:
    """
    Return a list of installed packages that are:
      - NOT in used_packages
      - NOT in declared_packages (user explicitly declared = keep)
      - NOT in _ALWAYS_KEEP
      - NOT protected by the caller
    """
    installed = get_all_installed()
    extra_protect = {_normalise(p) for p in (protected or set())}
    used_norm = {_normalise(p) for p in used_packages}
    declared_norm = {_normalise(p) for p in declared_packages}
    keep = {_normalise(p) for p in _ALWAYS_KEEP} | extra_protect

    removable: list[str] = []
    for pkg_name in installed:
        norm = _normalise(pkg_name)
        if norm in keep:
            continue
        if norm in used_norm or norm in declared_norm:
            continue
        removable.append(pkg_name)

    return sorted(removable, key=str.lower)


def uninstall_packages(
    packages: list[str],
    dry_run: bool = True,
) -> CleanResult:
    """
    Uninstall packages from the current Python environment.
    When dry_run=True, only reports what would be removed.
    """
    result = CleanResult(to_remove=packages, dry_run=dry_run)

    if dry_run or not packages:
        return result

    for pkg in packages:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                result.removed.append(pkg)
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                result.errors.append(f"{pkg}: {err}")
                result.skipped.append(pkg)
        except subprocess.TimeoutExpired:
            result.errors.append(f"{pkg}: uninstall timed out")
            result.skipped.append(pkg)
        except Exception as exc:
            result.errors.append(f"{pkg}: {exc}")
            result.skipped.append(pkg)

    return result


def clean_environment(
    used_packages: set[str],
    declared_packages: set[str],
    protected: Optional[set[str]] = None,
    dry_run: bool = True,
) -> CleanResult:
    """
    High-level entry: compute what to remove and optionally remove it.

    Parameters
    ----------
    used_packages:
        Packages confirmed used in source code (from scanner).
    declared_packages:
        Packages explicitly declared in requirements.txt / pyproject.toml.
    protected:
        Additional package names the caller wants to keep regardless.
    dry_run:
        When True (default), only compute + report — don't uninstall.
    """
    removable = compute_removable(used_packages, declared_packages, protected)
    return uninstall_packages(removable, dry_run=dry_run)