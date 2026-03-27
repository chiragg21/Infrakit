"""
infrakit.deps._scanner
~~~~~~~~~~~~~~~~~~~~~~
AST-based scanner that walks Python (and optionally Jupyter) files,
extracts imports, and checks whether the imported names are actually
referenced in the code body (conservative unused-import detection).
"""

from __future__ import annotations

import ast
import json
import tokenize
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

# ---------------------------------------------------------------------------
# Import ↔ pip-package name mapping
# Many packages are installed under a different name than their import name.
# ---------------------------------------------------------------------------
IMPORT_TO_PIP: dict[str, str] = {
    # Computer vision / image
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "skimage": "scikit-image",
    "imageio": "imageio",
    # ML / data science
    "sklearn": "scikit-learn",
    "xgb": "xgboost",
    "lightgbm": "lightgbm",
    "catboost": "catboost",
    "torch": "torch",
    "torchvision": "torchvision",
    "torchaudio": "torchaudio",
    "tensorflow": "tensorflow",
    "tf": "tensorflow",
    "keras": "keras",
    "transformers": "transformers",
    "diffusers": "diffusers",
    "datasets": "datasets",
    "accelerate": "accelerate",
    "peft": "peft",
    "sentence_transformers": "sentence-transformers",
    "faiss": "faiss-cpu",
    # Data
    "pd": "pandas",
    "pandas": "pandas",
    "np": "numpy",
    "numpy": "numpy",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
    "polars": "polars",
    "pyarrow": "pyarrow",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "xlwt": "xlwt",
    "xlsxwriter": "XlsxWriter",
    # Visualisation
    "matplotlib": "matplotlib",
    "mpl": "matplotlib",
    "plt": "matplotlib",
    "seaborn": "seaborn",
    "plotly": "plotly",
    "bokeh": "bokeh",
    "altair": "altair",
    "dash": "dash",
    "streamlit": "streamlit",
    "gradio": "gradio",
    # Web / API
    "flask": "Flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "starlette": "starlette",
    "django": "Django",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "requests": "requests",
    "urllib3": "urllib3",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "scrapy": "Scrapy",
    "pydantic": "pydantic",
    # Database / storage
    "sqlalchemy": "SQLAlchemy",
    "pymongo": "pymongo",
    "motor": "motor",
    "redis": "redis",
    "psycopg2": "psycopg2-binary",
    "psycopg": "psycopg",
    "pymysql": "PyMySQL",
    "cx_Oracle": "cx_Oracle",
    "boto3": "boto3",
    "botocore": "botocore",
    "google.cloud": "google-cloud",
    # CLI / config
    "click": "click",
    "typer": "typer",
    "rich": "rich",
    "colorama": "colorama",
    "tqdm": "tqdm",
    "dotenv": "python-dotenv",
    "yaml": "PyYAML",
    "toml": "toml",
    "tomllib": "tomli",          # stdlib in 3.11+, else tomli
    "decouple": "python-decouple",
    "environs": "environs",
    # Async
    "anyio": "anyio",
    "trio": "trio",
    "asyncio": "asyncio",        # stdlib – will be filtered anyway
    "celery": "celery",
    "kombu": "kombu",
    # Testing
    "pytest": "pytest",
    "hypothesis": "hypothesis",
    "factory_boy": "factory_boy",
    "faker": "Faker",
    "mock": "mock",              # stdlib in 3.3+
    "responses": "responses",
    "httpretty": "httpretty",
    # Serialisation
    "msgpack": "msgpack",
    "orjson": "orjson",
    "ujson": "ujson",
    "simplejson": "simplejson",
    "cbor2": "cbor2",
    "avro": "avro-python3",
    # Misc utilities
    "dateutil": "python-dateutil",
    "arrow": "arrow",
    "pendulum": "pendulum",
    "pytz": "pytz",
    "tzlocal": "tzlocal",
    "cryptography": "cryptography",
    "jwt": "PyJWT",
    "paramiko": "paramiko",
    "fabric": "fabric",
    "invoke": "invoke",
    "sh": "sh",
    "psutil": "psutil",
    "loguru": "loguru",
    "structlog": "structlog",
    "attr": "attrs",
    "attrs": "attrs",
    "cattrs": "cattrs",
    "dacite": "dacite",
    "marshmallow": "marshmallow",
    "cerberus": "Cerberus",
    "voluptuous": "voluptuous",
    "jsonschema": "jsonschema",
    "packaging": "packaging",
    "semver": "semver",
    "tabulate": "tabulate",
    "prettytable": "prettytable",
    "jinja2": "Jinja2",
    "mako": "Mako",
    "Mako": "Mako",
    "markupsafe": "MarkupSafe",
    "cachetools": "cachetools",
    "diskcache": "diskcache",
    "joblib": "joblib",
    "dill": "dill",
    "cloudpickle": "cloudpickle",
    "more_itertools": "more-itertools",
    "toolz": "toolz",
    "cytoolz": "cytoolz",
    "sortedcontainers": "sortedcontainers",
    "intervaltree": "intervaltree",
    "networkx": "networkx",
    "nx": "networkx",
    "igraph": "python-igraph",
    "shapely": "Shapely",
    "geopandas": "geopandas",
    "fiona": "Fiona",
    "pyproj": "pyproj",
    "rasterio": "rasterio",
    "sympy": "sympy",
    "numba": "numba",
    "numexpr": "numexpr",
    "cython": "Cython",
    "cffi": "cffi",
    "ctypes": "ctypes",          # stdlib
    "pybind11": "pybind11",
    "swig": "swig",
    "nox": "nox",
    "tox": "tox",
    "pre_commit": "pre-commit",
    "black": "black",
    "isort": "isort",
    "flake8": "flake8",
    "pylint": "pylint",
    "mypy": "mypy",
    "pyright": "pyright",
    "bandit": "bandit",
    "safety": "safety",
    "pip_audit": "pip-audit",
    "twine": "twine",
    "build": "build",
    "setuptools": "setuptools",
    "wheel": "wheel",
    "flit": "flit",
    "hatchling": "hatchling",
    "poetry": "poetry",
}

# Python stdlib top-level module names (3.8-3.12 superset)
_STDLIB_MODULES: frozenset[str] = frozenset({
    "__future__", "_thread", "abc", "aifc", "argparse", "array", "ast",
    "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64",
    "bdb", "binascii", "binhex", "bisect", "builtins", "bz2", "calendar",
    "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
    "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "cProfile", "csv",
    "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal",
    "difflib", "dis", "distutils", "doctest", "email", "encodings",
    "enum", "errno", "faulthandler", "fcntl", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "grp", "gzip", "hashlib", "heapq",
    "hmac", "html", "http", "idlelib", "imaplib", "imghdr", "imp",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
    "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
    "modulefinder", "multiprocessing", "netrc", "nis", "nntplib",
    "numbers", "operator", "optparse", "os", "ossaudiodev", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr", "socket",
    "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants",
    "sre_parse", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig",
    "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios",
    "test", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml",
    "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    # typing extensions that are sometimes separate packages
    "typing_extensions",
    # common internal/local prefixes to skip
    "_collections_abc", "_weakrefset",
})


def is_stdlib(module_root: str) -> bool:
    """Return True if the top-level module name is part of stdlib."""
    return module_root in _STDLIB_MODULES


def import_root(module_name: str) -> str:
    """Return the top-level package name, e.g. 'google.cloud.storage' → 'google'."""
    return module_name.split(".")[0]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ImportRecord:
    """One import statement found in a file."""
    module: str           # full module path, e.g. 'os.path' or 'numpy'
    alias: str            # local name used in code (None → same as last segment)
    names: list[str]      # for 'from x import a, b' → ['a', 'b']; else []
    lineno: int
    is_from: bool         # True for 'from x import y'
    file: Path
    is_relative: bool = False

    @property
    def root(self) -> str:
        return import_root(self.module)

    @property
    def pip_name(self) -> str:
        """Resolve to pip package name using the mapping table."""
        # Try full module first, then root
        return (
            IMPORT_TO_PIP.get(self.module)
            or IMPORT_TO_PIP.get(self.root)
            or self.root.replace("_", "-")
        )

    @property
    def local_names(self) -> list[str]:
        """Names that will be used in code to reference this import."""
        if self.names:
            return self.names
        return [self.alias or self.module.split(".")[-1]]


@dataclass
class FileAnalysis:
    path: Path
    imports: list[ImportRecord] = field(default_factory=list)
    # names used in the code body (identifiers, attributes)
    used_names: set[str] = field(default_factory=set)
    parse_error: Optional[str] = None


@dataclass
class ScanResult:
    files: list[FileAnalysis] = field(default_factory=list)
    # pip package name → set of files that use it
    used_packages: dict[str, set[Path]] = field(default_factory=dict)
    # pip package name → set of files that import but never reference it
    possibly_unused: dict[str, set[Path]] = field(default_factory=dict)
    # import names that couldn't be resolved to a known pip package
    unknown_imports: dict[str, set[Path]] = field(default_factory=dict)
    errors: list[tuple[Path, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _collect_used_names(tree: ast.AST) -> set[str]:
    """
    Walk the AST and collect every Name and Attribute identifier used
    in the code body (excluding Import/ImportFrom nodes themselves).
    """
    used: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_Import(self, node):
            pass  # skip — don't treat import names as "used"

        def visit_ImportFrom(self, node):
            pass  # skip

        def visit_Name(self, node):
            used.add(node.id)

        def visit_Attribute(self, node):
            # collect the root name for dotted access like np.array
            if isinstance(node.value, ast.Name):
                used.add(node.value.id)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return used


def _extract_imports(tree: ast.AST, filepath: Path) -> list[ImportRecord]:
    records: list[ImportRecord] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(ImportRecord(
                    module=alias.name,
                    alias=alias.asname or alias.name.split(".")[0],
                    names=[],
                    lineno=node.lineno,
                    is_from=False,
                    file=filepath,
                    is_relative=False,
                ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            aliases = node.names

            is_relative = node.level>0
            # from x import *  → treat module itself as the dep
            if any(a.name == "*" for a in aliases):
                records.append(ImportRecord(
                    module=module,
                    alias=module.split(".")[0],
                    names=["*"],
                    lineno=node.lineno,
                    is_from=True,
                    file=filepath,
                    is_relative=is_relative,
                ))
            else:
                imported_names = [a.asname or a.name for a in aliases]
                records.append(ImportRecord(
                    module=module,
                    alias=module.split(".")[0],
                    names=imported_names,
                    lineno=node.lineno,
                    is_from=True,
                    file=filepath,
                    is_relative=is_relative,
                ))

    return records


# ---------------------------------------------------------------------------
# Notebook support
# ---------------------------------------------------------------------------

def _extract_notebook_source(path: Path) -> str:
    """Extract all code cells from a .ipynb file as a single Python string."""
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot parse notebook JSON: {exc}") from exc

    lines: list[str] = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            src = cell.get("source", [])
            if isinstance(src, list):
                src = "".join(src)
            lines.append(src)
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------

def analyse_file(path: Path) -> FileAnalysis:
    analysis = FileAnalysis(path=path)

    try:
        if path.suffix == ".ipynb":
            source = _extract_notebook_source(path)
        else:
            source = path.read_text(encoding="utf-8", errors="replace")

        tree = ast.parse(source, filename=str(path))
        analysis.imports = _extract_imports(tree, path)
        analysis.used_names = _collect_used_names(tree)

    except SyntaxError as exc:
        analysis.parse_error = f"SyntaxError: {exc}"
    except Exception as exc:
        analysis.parse_error = str(exc)

    return analysis


# ---------------------------------------------------------------------------
# Scanner (walks a project directory)
# ---------------------------------------------------------------------------

def _should_include(path: Path, include_notebooks: bool) -> bool:
    if path.suffix == ".py":
        return True
    if include_notebooks and path.suffix == ".ipynb":
        return True
    return False


def scan_project(
    root: Path,
    include_notebooks: bool = False,
    gitignore_filter=None,          # callable(Path) → bool (True = ignored)
) -> ScanResult:
    """
    Walk *root*, analyse every eligible file, return a ScanResult.

    ``gitignore_filter`` should be a callable that returns True when a
    Path should be *excluded*.  When None, no gitignore filtering is applied.
    """
    result = ScanResult()

    files = _walk_files(root, include_notebooks, gitignore_filter)

    for filepath in files:
        analysis = analyse_file(filepath)
        result.files.append(analysis)

        if analysis.parse_error:
            result.errors.append((filepath, analysis.parse_error))
            continue

        for imp in analysis.imports:
            if is_stdlib(imp.root):
                continue  # stdlib — skip entirely

            if getattr(imp, "is_relative", False):
                continue

            pip = imp.pip_name
            unknown = pip == imp.root.replace("_", "-") and imp.root not in IMPORT_TO_PIP

            # Determine if the import is actually referenced in code
            local_names = imp.local_names
            is_star = "*" in local_names

            if is_star:
                # Can't tell — assume used
                actually_used = True
            else:
                actually_used = any(
                    name in analysis.used_names for name in local_names
                )

            if actually_used:
                result.used_packages.setdefault(pip, set()).add(filepath)
            else:
                result.possibly_unused.setdefault(pip, set()).add(filepath)

            if unknown and not is_stdlib(imp.root):
                result.unknown_imports.setdefault(pip, set()).add(filepath)

    # A package is "used" if it appears as used in ANY file.
    # Remove from possibly_unused those that are confirmed used elsewhere.
    for pkg in list(result.possibly_unused.keys()):
        if pkg in result.used_packages:
            del result.possibly_unused[pkg]

    return result


def _walk_files(
    root: Path,
    include_notebooks: bool,
    gitignore_filter,
) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not _should_include(path, include_notebooks):
            continue

        # Use forward-slash relative path for cross-platform consistency
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue

        parts = rel.parts   # tuple of path components, no slashes

        # Skip hidden dirs/files and common noise dirs
        if any(p.startswith(".") for p in parts):
            continue
        if any(p in ("__pycache__", ".venv", "venv", "env",
                     "node_modules", "dist", "build", ".tox", ".nox")
               for p in parts):
            continue

        # Gitignore filter: pass both the full relative path and each
        # directory component so patterns like "ignored/" match correctly
        if gitignore_filter:
            # Check the file itself and every ancestor directory component
            rel_posix = rel.as_posix()
            if gitignore_filter(rel_posix, parts):
                continue

        yield path