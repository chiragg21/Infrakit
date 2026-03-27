"""
infrakit.deps._health
~~~~~~~~~~~~~~~~~~~~~
Dependency health checks:
  - outdated packages (via PyPI JSON API)
  - security vulnerabilities (via pip-audit subprocess)
  - license compatibility (via pip show / importlib.metadata)
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
import importlib.metadata


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OutdatedPackage:
    name: str
    current: str
    latest: str
    status: str   # 'outdated' | 'up-to-date' | 'unknown' | 'not-installed'


@dataclass
class Vulnerability:
    package: str
    installed_version: str
    vuln_id: str
    description: str
    fix_version: str = ""


@dataclass
class LicenseInfo:
    package: str
    version: str
    license: str
    compatible: Optional[bool] = None   # None = unknown
    notes: str = ""


@dataclass
class HealthReport:
    outdated: list[OutdatedPackage] = field(default_factory=list)
    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    licenses: list[LicenseInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalise package name: lowercase, underscores → hyphens."""
    return name.lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Installed package versions
# ---------------------------------------------------------------------------

def get_installed_version(package: str) -> Optional[str]:
    """
    Return the installed version of a package, or None if not found.
    Tries the exact name first, then the normalised form (lower + hyphens).
    """
    for candidate in (package, _norm(package)):
        try:
            return importlib.metadata.version(candidate)
        except importlib.metadata.PackageNotFoundError:
            pass
    return None


def get_all_installed() -> dict[str, str]:
    """
    Return dict of normalised_package_name → version for every installed dist.
    Iterates importlib.metadata.distributions() which works on all platforms
    and Python 3.8+.
    """
    result: dict[str, str] = {}
    try:
        for dist in importlib.metadata.distributions():
            try:
                meta = dist.metadata
                name = meta.get("Name")
                version = meta.get("Version")
                if name and version:
                    result[_norm(str(name))] = str(version)
            except Exception:
                continue
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Outdated check (PyPI JSON API)
# ---------------------------------------------------------------------------

def _fetch_pypi_latest(package: str, timeout: int = 8) -> Optional[str]:
    """Query PyPI JSON API for the latest stable version of a package."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "infrakit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["info"]["version"]
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def _version_is_older(current: str, latest: str) -> bool:
    """
    Return True if current < latest.
    Uses packaging.version.Version when available; falls back to a
    pure-stdlib numeric tuple comparison so it never raises.
    """
    # packaging is often already installed (pip depends on it)
    try:
        from packaging.version import Version  # type: ignore
        return Version(current) < Version(latest)
    except Exception:
        pass

    # Pure-stdlib fallback: compare numeric segments only
    def _segments(v: str) -> tuple:
        parts = []
        for seg in v.split("."):
            digits = ""
            for ch in seg:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            parts.append(int(digits) if digits else 0)
        return tuple(parts)

    try:
        return _segments(current) < _segments(latest)
    except Exception:
        return current != latest


def check_outdated(
    packages: list[str],
    workers: int = 10,
) -> list[OutdatedPackage]:
    """
    Check PyPI for the latest version of each package.
    Returns a list of OutdatedPackage for every package checked.
    """
    installed = get_all_installed()

    def _check(pkg: str) -> OutdatedPackage:
        norm = _norm(pkg)
        current = installed.get(norm)

        if current is None:
            return OutdatedPackage(pkg, "not installed", "unknown", "not-installed")

        latest = _fetch_pypi_latest(pkg)
        if latest is None:
            return OutdatedPackage(pkg, current, "unknown", "unknown")

        status = "outdated" if _version_is_older(current, latest) else "up-to-date"
        return OutdatedPackage(pkg, current, latest, status)

    results: list[OutdatedPackage] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check, p): p for p in packages}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                pkg = futures[fut]
                results.append(OutdatedPackage(pkg, "error", "error", f"error: {exc}"))

    return sorted(results, key=lambda x: (x.status != "outdated", x.name.lower()))


# ---------------------------------------------------------------------------
# Security vulnerability scan (pip-audit)
# ---------------------------------------------------------------------------

def _parse_pip_audit_json(raw: str) -> list[Vulnerability]:
    vulns: list[Vulnerability] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return vulns

    for entry in data:
        pkg_name = entry.get("name", "")
        pkg_ver = entry.get("version", "")
        for v in entry.get("vulns", []):
            fix_vers = v.get("fix_versions", [])
            fix_str = ", ".join(fix_vers) if fix_vers else "no fix available"
            vulns.append(Vulnerability(
                package=pkg_name,
                installed_version=pkg_ver,
                vuln_id=v.get("id", ""),
                description=v.get("description", ""),
                fix_version=fix_str,
            ))

    return vulns


def check_vulnerabilities(
    packages: Optional[list[str]] = None,
) -> tuple[list[Vulnerability], Optional[str]]:
    """
    Run pip-audit and return (vulnerabilities, error_message).
    pip-audit must be installed: pip install pip-audit
    """
    try:
        chk = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if chk.returncode != 0:
            return [], "pip-audit is not installed. Run: pip install pip-audit"
    except FileNotFoundError:
        return [], "pip-audit is not installed. Run: pip install pip-audit"
    except subprocess.TimeoutExpired:
        return [], "pip-audit version check timed out"

    cmd = [sys.executable, "-m", "pip_audit", "--format=json", "--progress-spinner=off"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = proc.stdout or proc.stderr
        vulns = _parse_pip_audit_json(output)

        if packages:
            pkg_lower = {_norm(p) for p in packages}
            vulns = [v for v in vulns if _norm(v.package) in pkg_lower]

        return vulns, None

    except subprocess.TimeoutExpired:
        return [], "pip-audit timed out after 120s"
    except Exception as exc:
        return [], f"pip-audit error: {exc}"


# ---------------------------------------------------------------------------
# License check
# ---------------------------------------------------------------------------

_LICENSE_NOTES: dict[str, tuple[Optional[bool], str]] = {
    "mit": (True, "Permissive — safe for most projects"),
    "apache-2.0": (True, "Permissive with patent protection"),
    "apache 2.0": (True, "Permissive with patent protection"),
    "apache software": (True, "Permissive with patent protection"),
    "bsd-2-clause": (True, "Permissive"),
    "bsd-3-clause": (True, "Permissive"),
    "bsd": (True, "Permissive"),
    "isc": (True, "Permissive"),
    "python-2.0": (True, "Permissive (PSF)"),
    "psf": (True, "Python Software Foundation — permissive"),
    "unlicense": (True, "Public domain"),
    "cc0": (True, "Public domain"),
    "mpl-2.0": (None, "Weak copyleft — file-level, review for your use case"),
    "lgpl-2.0": (None, "Weak copyleft — dynamic linking usually OK"),
    "lgpl-2.1": (None, "Weak copyleft — dynamic linking usually OK"),
    "lgpl-3.0": (None, "Weak copyleft — dynamic linking usually OK"),
    "gpl-2.0": (False, "Strong copyleft — may require source disclosure"),
    "gpl-3.0": (False, "Strong copyleft — may require source disclosure"),
    "agpl-3.0": (False, "Network copyleft — very restrictive"),
    "proprietary": (False, "Proprietary — check license terms"),
    "commercial": (False, "Commercial — check license terms"),
}


def _normalise_license(raw: str) -> str:
    return raw.lower().strip().replace(" license", "").replace("license", "").strip()


def _get_package_license(package: str) -> tuple[str, str]:
    """Return (license_string, version) for an installed package."""
    for candidate in (package, _norm(package)):
        try:
            meta = importlib.metadata.metadata(candidate)
            version = str(meta.get("Version", "unknown"))
            lic = str(meta.get("License", "") or "")
            if not lic:
                for c in (meta.get_all("Classifier") or []):
                    if "License" in c:
                        lic = c.split("::")[-1].strip()
                        break
            return lic or "UNKNOWN", version
        except importlib.metadata.PackageNotFoundError:
            continue
    return "UNKNOWN", "unknown"


def check_licenses(packages: list[str]) -> list[LicenseInfo]:
    """Return license information for each package."""
    results: list[LicenseInfo] = []
    for pkg in packages:
        lic, ver = _get_package_license(pkg)
        norm = _normalise_license(lic)
        compatible, notes = _LICENSE_NOTES.get(
            norm, (None, "Unknown license — review manually")
        )
        results.append(LicenseInfo(
            package=pkg, version=ver, license=lic,
            compatible=compatible, notes=notes,
        ))
    return sorted(results, key=lambda x: (x.compatible is not False, x.package.lower()))


# ---------------------------------------------------------------------------
# Combined health check
# ---------------------------------------------------------------------------

def run_health_check(
    packages: list[str],
    check_outdated_flag: bool = True,
    check_vulns_flag: bool = True,
    check_licenses_flag: bool = True,
) -> HealthReport:
    report = HealthReport()
    if check_outdated_flag:
        report.outdated = check_outdated(packages)
    if check_vulns_flag:
        vulns, err = check_vulnerabilities(packages)
        report.vulnerabilities = vulns
        if err:
            report.errors.append(f"Security scan: {err}")
    if check_licenses_flag:
        report.licenses = check_licenses(packages)
    return report