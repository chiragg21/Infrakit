"""
infrakit.deps.depfile
~~~~~~~~~~~~~~~~~~~~~~
Read and write dependency files: requirements.txt and pyproject.toml.
Auto-detects which format(s) are present in the project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PinnedDep:
    """One dependency entry as found in a dep file."""
    name: str               # normalised pip name
    raw: str                # original line / string as-is
    version_spec: str = ""  # e.g. '>=1.2,<2' or '==1.4.0' or ''
    extras: list[str] = field(default_factory=list)   # e.g. ['security']
    markers: str = ""       # environment markers

    @property
    def normalised(self) -> str:
        """Lower-cased, hyphens-normalised name for comparison."""
        return self.name.lower().replace("_", "-")


@dataclass
class DepFile:
    """In-memory representation of a parsed dependency file."""
    path: Path
    format: str             # 'requirements' | 'pyproject'
    deps: list[PinnedDep] = field(default_factory=list)
    # For pyproject.toml we preserve the full raw text for round-trip writes
    _raw_text: str = field(default="", repr=False)


# ---------------------------------------------------------------------------
# requirements.txt parsing
# ---------------------------------------------------------------------------

# Matches:  package[extras]>=version ; marker  # comment
_REQ_LINE = re.compile(
    r"""
    ^
    (?P<name>[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)   # package name
    (?:\[(?P<extras>[^\]]+)\])?                             # optional [extras]
    (?P<spec>[^;#\n]*)                                      # version specifier
    (?:;(?P<marker>[^#\n]*))?                               # env marker
    """,
    re.VERBOSE,
)


def _parse_requirements(path: Path) -> DepFile:
    deps: list[PinnedDep] = []
    text = path.read_text(encoding="utf-8")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        # Skip comments, blank lines, options (-r, --index-url, etc.)
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Skip VCS / URL requirements
        if line.startswith(("git+", "http://", "https://", "file://")):
            continue

        m = _REQ_LINE.match(line)
        if not m:
            continue

        name = m.group("name").strip()
        extras_raw = m.group("extras") or ""
        spec = (m.group("spec") or "").strip()
        marker = (m.group("marker") or "").strip()
        extras = [e.strip() for e in extras_raw.split(",") if e.strip()]

        deps.append(PinnedDep(
            name=name,
            raw=raw_line,
            version_spec=spec,
            extras=extras,
            markers=marker,
        ))

    return DepFile(path=path, format="requirements", deps=deps, _raw_text=text)


# ---------------------------------------------------------------------------
# pyproject.toml parsing
# A lightweight parser — we deliberately avoid requiring `tomllib`/`tomli`
# here so the module has zero extra deps.  We only need the [project]
# dependencies table and [tool.poetry.dependencies].
# ---------------------------------------------------------------------------

_TOML_STRING = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'')
_INLINE_COMMENT = re.compile(r'#.*$')

# Matches: "package>=1.0"  or  package = ">=1.0"  (poetry style)
_PEP508 = re.compile(
    r"""
    ^
    (?P<name>[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)
    (?:\[(?P<extras>[^\]]+)\])?
    (?P<spec>[^;#\n]*)
    (?:;(?P<marker>[^#\n]*))?
    """,
    re.VERBOSE,
)


def _strip_toml_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_pep508(raw: str) -> Optional[PinnedDep]:
    raw = raw.strip().strip('"\'').strip()
    if not raw or raw.startswith("#"):
        return None
    # Skip VCS / URL
    if any(raw.startswith(p) for p in ("git+", "http://", "https://", "file://")):
        return None
    m = _PEP508.match(raw)
    if not m:
        return None
    name = m.group("name").strip()
    if not name:
        return None
    extras_raw = m.group("extras") or ""
    spec = (m.group("spec") or "").strip()
    marker = (m.group("marker") or "").strip()
    extras = [e.strip() for e in extras_raw.split(",") if e.strip()]
    return PinnedDep(name=name, raw=raw, version_spec=spec, extras=extras, markers=marker)


def _parse_pyproject(path: Path) -> DepFile:
    text = path.read_text(encoding="utf-8")
    deps: list[PinnedDep] = []

    lines = text.splitlines()
    n = len(lines)
    i = 0

    # We look for three patterns:
    # 1. [project]  → dependencies = [ ... ]
    # 2. [project.optional-dependencies.*]  → list
    # 3. [tool.poetry.dependencies]  → key = "version"
    # 4. [tool.poetry.*.dependencies]  → same

    in_section: Optional[str] = None  # 'pep621' | 'poetry' | None
    in_array = False

    while i < n:
        line = lines[i]
        stripped = line.strip()
        comment_stripped = _INLINE_COMMENT.sub("", stripped).strip()

        # Detect section headers
        if stripped.startswith("["):
            header = stripped.strip("[]").strip()
            if header == "project" or header.startswith("project.optional"):
                in_section = "pep621"
            elif "poetry" in header and "dependencies" in header:
                in_section = "poetry"
            else:
                in_section = None
            in_array = False
            i += 1
            continue

        if in_section == "pep621":
            # Look for:  dependencies = [
            if re.match(r'dependencies\s*=\s*\[', comment_stripped):
                in_array = True
                # Check if array closes on same line
                rest = comment_stripped[comment_stripped.index("[") + 1:]
                if "]" in rest:
                    # single-line array
                    items = rest[: rest.index("]")]
                    for raw in re.split(r',', items):
                        d = _parse_pep508(raw)
                        if d:
                            deps.append(d)
                    in_array = False
                i += 1
                continue

            if in_array:
                if "]" in comment_stripped:
                    # last item possibly before ]
                    item = comment_stripped[: comment_stripped.index("]")]
                    d = _parse_pep508(item)
                    if d:
                        deps.append(d)
                    in_array = False
                else:
                    d = _parse_pep508(comment_stripped)
                    if d:
                        deps.append(d)
                i += 1
                continue

        elif in_section == "poetry":
            # Skip python = "..." entries
            if comment_stripped.lower().startswith("python"):
                i += 1
                continue
            # key = "version_or_constraint"
            m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*(.+)$', comment_stripped)
            if m:
                name = m.group(1)
                val = _strip_toml_quotes(m.group(2))
                # poetry can have inline table: {version = "...", extras = [...]}
                if val.startswith("{"):
                    # extract version from inline table
                    vm = re.search(r'version\s*=\s*["\']([^"\']+)["\']', val)
                    spec = vm.group(1) if vm else ""
                    em = re.search(r'extras\s*=\s*\[([^\]]+)\]', val)
                    extras = [e.strip().strip('"\'') for e in em.group(1).split(",") if e.strip()] if em else []
                else:
                    spec = val if val not in ("*", "latest") else ""
                    extras = []
                deps.append(PinnedDep(
                    name=name,
                    raw=comment_stripped,
                    version_spec=spec,
                    extras=extras,
                ))
            i += 1
            continue

        i += 1

    return DepFile(path=path, format="pyproject", deps=deps, _raw_text=text)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def find_dep_files(root: Path) -> list[DepFile]:
    """Find and parse all dependency files in *root* (non-recursive)."""
    found: list[DepFile] = []

    req = root / "requirements.txt"
    if req.exists():
        found.append(_parse_requirements(req))

    # Also check common variants
    for name in ("requirements-dev.txt", "requirements_dev.txt",
                 "requirements-test.txt", "requirements_test.txt"):
        p = root / name
        if p.exists():
            found.append(_parse_requirements(p))

    pyproj = root / "pyproject.toml"
    if pyproj.exists():
        found.append(_parse_pyproject(pyproj))

    return found


def all_declared_packages(dep_files: list[DepFile]) -> dict[str, PinnedDep]:
    """Return dict of normalised-name → PinnedDep from all dep files combined."""
    out: dict[str, PinnedDep] = {}
    for df in dep_files:
        for dep in df.deps:
            out[dep.normalised] = dep
    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_requirements(
    packages: list[str],          # pip names to include
    declared: dict[str, PinnedDep],
    output_path: Path,
    keep_versions: bool = True,
) -> None:
    """Write a clean requirements.txt with only *packages*."""
    lines: list[str] = [
        "# Generated by infrakit deps export",
        "# Only packages actively used in this project",
        "",
    ]
    for pkg in sorted(packages, key=str.lower):
        norm = pkg.lower().replace("_", "-")
        pinned = declared.get(norm)
        if pinned and keep_versions and pinned.version_spec:
            extras = f"[{','.join(pinned.extras)}]" if pinned.extras else ""
            marker = f" ; {pinned.markers}" if pinned.markers else ""
            pinned.version_spec = pinned.version_spec.strip().strip('",')
            lines.append(f"{pkg}{extras}{pinned.version_spec}{marker}")
        else:
            lines.append(pkg)

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_requirements_inplace(
    dep_file: DepFile,
    used_packages: set[str],   # normalised names
) -> None:
    """Rewrite requirements.txt keeping only used packages (preserves ordering & comments)."""
    assert dep_file.format == "requirements"
    original = dep_file.path.read_text(encoding="utf-8")
    out_lines: list[str] = []

    for line in original.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            out_lines.append(line)
            continue
        m = _REQ_LINE.match(stripped)
        if not m:
            out_lines.append(line)
            continue
        name = m.group("name").strip().lower().replace("_", "-")
        if name in used_packages:
            out_lines.append(line)
        # else: drop the line (unused dep)

    dep_file.path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def update_pyproject_inplace(
    dep_file: DepFile,
    used_packages: set[str],   # normalised names
) -> None:
    """
    Rewrite pyproject.toml removing deps not in used_packages.
    Uses line-level editing to avoid toml-write library requirement.
    """
    assert dep_file.format == "pyproject"
    text = dep_file._raw_text
    lines = text.splitlines()
    out: list[str] = []

    in_dep_array = False
    in_poetry_deps = False

    for line in lines:
        stripped = line.strip()
        comment_stripped = _INLINE_COMMENT.sub("", stripped).strip()

        # Section transitions
        if stripped.startswith("["):
            in_dep_array = False
            in_poetry_deps = False
            header = stripped.strip("[]").strip()
            if "poetry" in header and "dependencies" in header:
                in_poetry_deps = True
            out.append(line)
            continue

        # PEP 621 dependency array
        if re.match(r'dependencies\s*=\s*\[', comment_stripped):
            in_dep_array = True
            if "]" in comment_stripped:
                in_dep_array = False
            out.append(line)
            continue

        if in_dep_array:
            if "]" in comment_stripped:
                in_dep_array = False
                out.append(line)
                continue
            d = _parse_pep508(comment_stripped)
            if d is None:
                out.append(line)
            elif d.normalised in used_packages:
                out.append(line)
            # else: drop unused dep line
            continue

        if in_poetry_deps:
            if stripped.startswith("["):
                in_poetry_deps = False
                out.append(line)
                continue
            m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=', comment_stripped)
            if m:
                name = m.group(1).lower().replace("_", "-")
                if name == "python" or name in used_packages:
                    out.append(line)
                # else: drop
                continue

        out.append(line)

    dep_file.path.write_text("\n".join(out) + "\n", encoding="utf-8")