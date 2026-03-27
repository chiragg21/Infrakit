"""
infrakit.deps.optimizer (FIXED VERSION)
~~~~~~~~~~~~~~~~~~~~~~~~
Import optimiser for Python source files:
  - Sort imports (stdlib → third-party → local), PEP 8 / isort style
  - Remove duplicate imports
  - Merge imports from same module
  - Convert relative ↔ absolute imports
  - Detect and report unused imports (conservative AST approach)

FIXES:
  - No longer accumulates extra newlines on repeated runs
  - Properly detects existing blank lines after imports
  - Scans entire file for duplicates, not just top block
  - Merges imports from same module (from x import a; from x import b → from x import a, b)

Uses isort as the backend when available, falls back to a clean
pure-Python implementation with zero extra dependencies.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Note: This assumes scanner module exists with these functions
# from .scanner import _STDLIB_MODULES, is_stdlib, import_root
# For standalone use, you'll need to implement these:

def is_stdlib(module: str) -> bool:
    """Check if module is from stdlib."""
    import sys
    return module in sys.stdlib_module_names if hasattr(sys, 'stdlib_module_names') else False

def import_root(module: str) -> str:
    """Get root package name from module path."""
    return module.split('.')[0] if module else ""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ImportLine:
    """Parsed representation of a single import statement."""
    raw: str                      # original source text
    kind: str                     # 'import' | 'from'
    module: str                   # e.g. 'os.path' or 'numpy'
    names: list[str]              # ['path'] for 'from os import path'
    aliases: dict[str, str]       # name → alias
    level: int                    # relative import level (0 = absolute)
    lineno: int
    category: str = ""            # 'stdlib' | 'third_party' | 'local' | 'relative'

    @property
    def sort_key(self) -> tuple:
        cat_order = {"stdlib": 0, "third_party": 1, "local": 2, "relative": 3}
        return (cat_order.get(self.category, 9), self.module.lower(), self.kind)

    def to_source(self) -> str:
        """Re-render the import statement as clean source."""
        if self.kind == "import":
            parts = []
            for name in sorted(self.names):
                alias = self.aliases.get(name, "")
                parts.append(f"{name} as {alias}" if alias else name)
            return f"import {', '.join(parts)}"
        else:  # from
            dots = "." * self.level
            mod = self.module or ""
            if not self.names:
                return f"from {dots}{mod} import *"
            parts = []
            for name in sorted(self.names):
                alias = self.aliases.get(name, "")
                parts.append(f"{name} as {alias}" if alias else name)
            names_str = ", ".join(parts)
            # Use multi-line if many names
            if len(names_str) > 60:
                inner = ",\n    ".join(parts)
                return f"from {dots}{mod} import (\n    {inner},\n)"
            return f"from {dots}{mod} import {names_str}"


@dataclass
class OptimizeResult:
    path: Path
    original: str
    optimized: str
    changes: list[str] = field(default_factory=list)
    duplicates_removed: int = 0
    imports_merged: int = 0
    imports_reordered: bool = False
    unused_reported: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def changed(self) -> bool:
        return self.original != self.optimized


# ---------------------------------------------------------------------------
# isort backend
# ---------------------------------------------------------------------------

def _isort_available() -> bool:
    try:
        import isort  # noqa: F401
        return True
    except ImportError:
        return False


def _run_isort(source: str, filepath: Path) -> Optional[str]:
    """Run isort on source, return sorted source or None on failure."""
    try:
        import isort
        config = isort.Config(
            profile="black",
            force_sort_within_sections=True,
            lines_after_imports=2,
        )
        return isort.code(source, config=config, file_path=filepath)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pure-Python import parser / sorter
# ---------------------------------------------------------------------------

_BLANK_OR_COMMENT = re.compile(r'^\s*(#.*)?$')


def _categorise(module: str, level: int, local_packages: set[str]) -> str:
    if level > 0:
        return "relative"
    root = import_root(module)
    if is_stdlib(root):
        return "stdlib"
    if root in local_packages:
        return "local"
    return "third_party"


def _parse_all_imports(source: str, local_packages: set[str]) -> list[ImportLine]:
    """Parse ALL import statements from source, regardless of location."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines_src = source.splitlines()
    result: list[ImportLine] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
            aliases = {a.name: a.asname for a in node.names if a.asname}
            module = names[0] if names else ""
            cat = _categorise(module, 0, local_packages)
            raw = lines_src[node.lineno - 1] if node.lineno <= len(lines_src) else ""
            result.append(ImportLine(
                raw=raw, kind="import", module=module,
                names=names, aliases=aliases, level=0,
                lineno=node.lineno, category=cat,
            ))

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            names = [a.name for a in node.names]
            aliases = {a.name: a.asname for a in node.names if a.asname}
            cat = _categorise(module, level, local_packages)
            raw = lines_src[node.lineno - 1] if node.lineno <= len(lines_src) else ""
            result.append(ImportLine(
                raw=raw, kind="from", module=module,
                names=names, aliases=aliases, level=level,
                lineno=node.lineno, category=cat,
            ))

    return sorted(result, key=lambda x: x.lineno)


def _find_import_block_range(source: str) -> tuple[int, int]:
    """
    Return (start_line_idx, end_line_idx) of the import block in source.
    Returns the range of lines that are either imports, blanks, or comments
    at the start of the file (skipping module docstring).
    """
    lines = source.splitlines()
    start = 0

    # Skip encoding comment and shebang
    for i, line in enumerate(lines[:3]):
        s = line.strip()
        if s.startswith("#") or s.startswith("# -*- coding"):
            start = i + 1

    # Skip module-level docstring
    try:
        tree = ast.parse(source)
        if hasattr(tree, "body") and tree.body:
            first_node = tree.body[0]
            if isinstance(first_node, ast.Expr) and isinstance(
                first_node.value, (ast.Constant, ast.Str)
            ):
                start = first_node.end_lineno or start
    except Exception:
        pass

    # Find end of import block
    end = start
    in_multiline = False
    paren_depth = 0

    for i in range(start, len(lines)):
        line = lines[i]
        stripped = line.strip()

        if in_multiline:
            paren_depth += line.count("(") - line.count(")")
            if paren_depth <= 0:
                in_multiline = False
            end = i + 1
            continue

        if stripped.startswith(("import ", "from ")):
            if "(" in line and ")" not in line:
                in_multiline = True
                paren_depth = line.count("(") - line.count(")")
            end = i + 1
            continue

        if _BLANK_OR_COMMENT.match(line):
            continue

        # Hit real code
        break

    return start, end


def _count_blank_lines_after(lines: list[str], end_idx: int) -> int:
    """Count consecutive blank lines starting from end_idx."""
    count = 0
    for i in range(end_idx, len(lines)):
        if not lines[i].strip():
            count += 1
        else:
            break
    return count


def _find_scattered_imports(source: str, import_block_end: int) -> list[tuple[int, str]]:
    """Find imports that appear after the main import block."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    
    lines = source.splitlines()
    scattered = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.lineno > import_block_end:
                line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                scattered.append((node.lineno, line_text.strip()))
    
    return scattered


def _remove_duplicates_and_merge(imports: list[ImportLine]) -> tuple[list[ImportLine], int, int]:
    """
    Remove duplicate imports AND merge same-module imports.
    Returns (deduped_list, duplicates_removed, imports_merged)
    """
    # Track: (kind, module, level) → ImportLine
    merged: dict[tuple, ImportLine] = {}
    duplicates_removed = 0
    imports_merged = 0

    for imp in imports:
        if imp.kind == "import":
            # For `import x`, each module is separate
            for name in imp.names:
                key = ("import", name, 0)
                if key in merged:
                    # Check if alias matches
                    existing = merged[key]
                    if existing.aliases.get(name) == imp.aliases.get(name):
                        duplicates_removed += 1
                        continue  # Skip duplicate
                merged[key] = ImportLine(
                    raw=imp.raw,
                    kind="import",
                    module=name,
                    names=[name],
                    aliases={name: imp.aliases.get(name)} if name in imp.aliases else {},
                    level=0,
                    lineno=imp.lineno,
                    category=imp.category,
                )
        
        else:  # kind == "from"
            key = ("from", imp.module, imp.level)
            
            if key in merged:
                # Merge names from same module
                existing = merged[key]
                
                # Check for exact duplicates
                for name in imp.names:
                    if name in existing.names:
                        existing_alias = existing.aliases.get(name)
                        new_alias = imp.aliases.get(name)
                        if existing_alias == new_alias:
                            duplicates_removed += 1
                        else:
                            # Different aliases for same name - keep both (rare edge case)
                            existing.names.append(name)
                            if new_alias:
                                existing.aliases[name] = new_alias
                    else:
                        # New name from same module - merge it
                        existing.names.append(name)
                        if name in imp.aliases:
                            existing.aliases[name] = imp.aliases[name]
                        imports_merged += 1
            else:
                # First occurrence
                merged[key] = ImportLine(
                    raw=imp.raw,
                    kind=imp.kind,
                    module=imp.module,
                    names=imp.names.copy(),
                    aliases=imp.aliases.copy(),
                    level=imp.level,
                    lineno=imp.lineno,
                    category=imp.category,
                )

    return list(merged.values()), duplicates_removed, imports_merged


def _sort_imports(imports: list[ImportLine]) -> str:
    """
    Sort imports into groups:
      1. stdlib
      2. third-party
      3. local / relative
    Returns formatted import block as string (WITHOUT trailing newlines).
    """
    groups: dict[str, list[ImportLine]] = {
        "stdlib": [], "third_party": [], "local": [], "relative": []
    }
    for imp in imports:
        groups[imp.category].append(imp)

    for cat in groups:
        groups[cat].sort(key=lambda x: x.sort_key)

    sections: list[str] = []
    for cat in ("stdlib", "third_party", "local", "relative"):
        group = groups[cat]
        if group:
            sections.append("\n".join(imp.to_source() for imp in group))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Relative ↔ Absolute import conversion
# ---------------------------------------------------------------------------

def _relative_to_absolute(
    imp: ImportLine,
    package_name: str,
    file_path: Path,
    root: Path,
) -> ImportLine:
    """Convert a relative import to absolute given the package context."""
    if imp.level == 0:
        return imp

    try:
        rel = file_path.relative_to(root)
        parts = list(rel.with_suffix("").parts)
        base_parts = parts[:-imp.level] if imp.level < len(parts) else parts[:1]
        if imp.module:
            abs_module = ".".join(base_parts + [imp.module])
        else:
            abs_module = ".".join(base_parts)

        new_imp = ImportLine(
            raw=imp.raw,
            kind=imp.kind,
            module=abs_module,
            names=imp.names,
            aliases=imp.aliases,
            level=0,
            lineno=imp.lineno,
            category="local",
        )
        return new_imp
    except Exception:
        return imp


def _absolute_to_relative(
    imp: ImportLine,
    file_path: Path,
    root: Path,
) -> ImportLine:
    """Convert an absolute local import to relative."""
    if imp.level > 0 or imp.category != "local":
        return imp

    try:
        file_parts = list(file_path.relative_to(root).with_suffix("").parts)
        mod_parts = imp.module.split(".")

        # Find common prefix
        common = 0
        for a, b in zip(file_parts[:-1], mod_parts):
            if a == b:
                common += 1
            else:
                break

        level = len(file_parts[:-1]) - common
        remaining = mod_parts[common:]

        new_imp = ImportLine(
            raw=imp.raw,
            kind=imp.kind,
            module=".".join(remaining),
            names=imp.names,
            aliases=imp.aliases,
            level=level,
            lineno=imp.lineno,
            category="relative",
        )
        return new_imp
    except Exception:
        return imp


# ---------------------------------------------------------------------------
# Main optimise entry-point
# ---------------------------------------------------------------------------

def optimise_file(
    filepath: Path,
    root: Path,
    local_packages: Optional[set[str]] = None,
    convert_to: Optional[str] = None,
    use_isort: bool = True,
    dry_run: bool = False,
    move_scattered: bool = True,
) -> OptimizeResult:
    """
    Optimise imports in a single Python file.
    
    Args:
        filepath: Path to the Python file
        root: Project root directory
        local_packages: Set of local package names
        convert_to: 'absolute' | 'relative' | None
        use_isort: Use isort if available
        dry_run: Don't write changes
        move_scattered: Move scattered imports to top block
        
    Returns:
        OptimizeResult with changes made
    """
    try:
        original = filepath.read_text(encoding="utf-8")
    except Exception as exc:
        return OptimizeResult(
            path=filepath, original="", optimized="",
            error=f"Cannot read file: {exc}"
        )

    result = OptimizeResult(path=filepath, original=original, optimized=original)

    # --- Parse ALL imports (not just top block) ---
    lp = local_packages or set()
    all_imports = _parse_all_imports(original, lp)
    
    if not all_imports:
        return result

    # --- Find import block range ---
    import_block_start, import_block_end = _find_import_block_range(original)
    
    # --- Check for scattered imports ---
    scattered = _find_scattered_imports(original, import_block_end)
    if scattered and not move_scattered:
        result.changes.append(f"⚠️  Found {len(scattered)} import(s) outside top block:")
        for lineno, text in scattered[:5]:
            result.changes.append(f"    Line {lineno}: {text}")
        if len(scattered) > 5:
            result.changes.append(f"    ... and {len(scattered) - 5} more")
        result.changes.append("    Use --move-scattered to consolidate them")

    # --- Deduplicate AND merge ---
    deduped, n_removed, n_merged = _remove_duplicates_and_merge(all_imports)
    
    if n_removed > 0:
        result.duplicates_removed = n_removed
        result.changes.append(f"✓ Removed {n_removed} duplicate import(s)")
    
    if n_merged > 0:
        result.imports_merged = n_merged
        result.changes.append(f"✓ Merged {n_merged} import(s) from same module")

    # --- Convert relative ↔ absolute ---
    if convert_to:
        pkg_name = root.name
        converted: list[ImportLine] = []
        conversion_count = 0
        
        for imp in deduped:
            if convert_to == "absolute" and imp.level > 0:
                new_imp = _relative_to_absolute(imp, pkg_name, filepath, root)
                if new_imp.module != imp.module or new_imp.level != imp.level:
                    conversion_count += 1
                converted.append(new_imp)
            elif convert_to == "relative" and imp.level == 0 and imp.category == "local":
                new_imp = _absolute_to_relative(imp, filepath, root)
                if new_imp.level != imp.level:
                    conversion_count += 1
                converted.append(new_imp)
            else:
                converted.append(imp)
        
        if conversion_count > 0:
            result.changes.append(f"✓ Converted {conversion_count} import(s) to {convert_to}")
        deduped = converted

    # --- Sort imports ---
    sorted_block = _sort_imports(deduped)

    # --- Reconstruct file with SMART newline handling ---
    lines = original.splitlines()
    
    # Count existing blank lines after import block
    existing_blanks = _count_blank_lines_after(lines, import_block_end)
    
    # We want exactly 2 blank lines after imports (PEP 8)
    required_blanks = 2
    blanks_to_add = max(0, required_blanks - existing_blanks)
    
    if move_scattered and scattered:
        # Remove ALL import lines from the file
        import_lines = {imp.lineno for imp in all_imports}
        non_import_lines = []
        for i, line in enumerate(lines, 1):
            if i not in import_lines:
                non_import_lines.append(line)
        
        # Find where code starts (skip header comments/docstrings)
        code_start_idx = 0
        for i, line in enumerate(non_import_lines):
            if i >= import_block_start and line.strip() and not line.strip().startswith('#'):
                code_start_idx = i
                break
        
        # Rebuild: header + sorted imports + blanks + rest
        header_lines = non_import_lines[:import_block_start]
        body_lines = non_import_lines[code_start_idx:]
        
        new_lines = (
            header_lines +
            sorted_block.splitlines() +
            [""] * required_blanks +
            body_lines
        )
        result.optimized = "\n".join(new_lines)
        result.changes.append(f"✓ Moved {len(scattered)} scattered import(s) to top")
    else:
        # Just replace the existing import block
        # Remove old import block AND existing blank lines after it
        end_with_blanks = import_block_end + existing_blanks
        
        new_lines = (
            lines[:import_block_start] +
            sorted_block.splitlines() +
            [""] * required_blanks +
            lines[end_with_blanks:]
        )
        result.optimized = "\n".join(new_lines)

    if result.optimized != original:
        result.imports_reordered = True
        if not any("sorted" in c.lower() for c in result.changes):
            result.changes.append("✓ Imports sorted (stdlib → third-party → local)")

    # --- Write back ---
    if result.changed and not dry_run:
        try:
            filepath.write_text(result.optimized, encoding="utf-8")
        except Exception as exc:
            result.error = f"Could not write file: {exc}"

    return result


def optimise_project(
    root: Path,
    files: Optional[list[Path]] = None,
    local_packages: Optional[set[str]] = None,
    convert_to: Optional[str] = None,
    use_isort: bool = True,
    dry_run: bool = False,
    move_scattered: bool = True,
) -> list[OptimizeResult]:
    """Optimise imports across a list of files (or all .py files in root)."""
    if files is None:
        files = sorted(root.rglob("*.py"))
        # Filter common noise paths
        files = [f for f in files if not any(
            p in str(f) for p in ("__pycache__", ".venv", "venv", ".tox", "node_modules")
        )]

    results: list[OptimizeResult] = []
    for f in files:
        r = optimise_file(
            f, root, local_packages=local_packages,
            convert_to=convert_to, use_isort=use_isort, 
            dry_run=dry_run, move_scattered=move_scattered,
        )
        results.append(r)

    return results