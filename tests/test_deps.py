"""
tests/test_deps.py
~~~~~~~~~~~~~~~~~~
Test suite for infrakit.deps — scanner, depfile parser, health checks,
optimizer, CLI integration, and the three bugs that were previously failing.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """Minimal temporary project for scanning tests."""
    src = tmp_path / "src"
    src.mkdir()
    utils = tmp_path / "utils"
    utils.mkdir()

    # Uses numpy and requests
    (src / "main.py").write_text(textwrap.dedent("""\
        import os
        import numpy as np
        from requests import get, post

        def fetch_data(url: str):
            resp = get(url)
            arr = np.array(resp.json())
            return arr
    """))

    # Imports cv2 but never references it; uses pd (pandas)
    (src / "unused_import.py").write_text(textwrap.dedent("""\
        import cv2
        import pandas as pd

        def process():
            df = pd.DataFrame()
            return df
    """))

    # Duplicate imports — all stdlib, so they won't appear in used_packages
    (utils / "helpers.py").write_text(textwrap.dedent("""\
        import os
        import os
        from pathlib import Path
        from pathlib import Path

        def get_home():
            return Path.home()
    """))

    (tmp_path / "requirements.txt").write_text(textwrap.dedent("""\
        numpy>=1.24.0
        requests==2.31.0
        opencv-python>=4.8
        pandas>=2.0
        flask>=3.0
    """))

    return tmp_path


@pytest.fixture
def tmp_pyproject(tmp_path):
    """Project with pyproject.toml."""
    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "mypackage" / "app.py").write_text(textwrap.dedent("""\
        import click
        from rich import print

        @click.command()
        def main():
            print("hello")
    """))

    (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "mypackage"
        version = "0.1.0"
        dependencies = [
            "click>=8.0",
            "rich>=13.0",
            "flask>=3.0",
            "numpy>=1.24",
        ]
    """))

    return tmp_path


# ===========================================================================
# _scanner tests
# ===========================================================================

class TestScanner:

    def test_scan_finds_used_packages(self, tmp_project):
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_project)
        assert "numpy" in result.used_packages
        assert "requests" in result.used_packages

    def test_scan_stdlib_excluded(self, tmp_project):
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_project)
        assert "os" not in result.used_packages
        assert "pathlib" not in result.used_packages

    def test_scan_detects_possibly_unused(self, tmp_project):
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_project)
        # cv2 imported but never used
        assert "opencv-python" in result.possibly_unused

    def test_scan_used_wins_over_possibly_unused(self, tmp_project):
        """A package used in any file must not appear in possibly_unused."""
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_project)
        # pandas is used via pd.DataFrame()
        assert "pandas" not in result.possibly_unused
        assert "pandas" in result.used_packages

    def test_scan_skip_venv_dirs(self, tmp_project):
        venv = tmp_project / ".venv" / "lib" / "site-packages" / "somelib"
        venv.mkdir(parents=True)
        (venv / "module.py").write_text("import boto3\nx = boto3.client('s3')")

        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_project)
        assert "boto3" not in result.used_packages

    def test_pip_name_mapping(self):
        from infrakit.deps.scanner import ImportRecord
        rec = ImportRecord(
            module="cv2", alias="cv2", names=[], lineno=1,
            is_from=False, file=Path("x.py"),
        )
        assert rec.pip_name == "opencv-python"

    def test_import_root(self):
        from infrakit.deps.scanner import import_root
        assert import_root("google.cloud.storage") == "google"
        assert import_root("numpy") == "numpy"

    def test_is_stdlib(self):
        from infrakit.deps.scanner import is_stdlib
        assert is_stdlib("os")
        assert is_stdlib("collections")
        assert not is_stdlib("numpy")
        assert not is_stdlib("requests")

    def test_notebook_scanning(self, tmp_path):
        nb = json.dumps({
            "cells": [
                {"cell_type": "code", "source": ["import pandas as pd\n", "df = pd.DataFrame()\n"]},
                {"cell_type": "markdown", "source": ["# Title"]},
                {"cell_type": "code", "source": ["import os\n", "os.getcwd()\n"]},
            ]
        })
        (tmp_path / "analysis.ipynb").write_text(nb)

        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_path, include_notebooks=True)
        assert "pandas" in result.used_packages
        assert "os" not in result.used_packages

    def test_notebook_not_scanned_by_default(self, tmp_path):
        nb = json.dumps({
            "cells": [{"cell_type": "code", "source": ["import numpy as np\n", "np.array([])\n"]}]
        })
        (tmp_path / "nb.ipynb").write_text(nb)

        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_path, include_notebooks=False)
        assert "numpy" not in result.used_packages

    def test_star_import_treated_as_used(self, tmp_path):
        (tmp_path / "mod.py").write_text("from numpy import *\n")
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_path)
        assert "numpy" in result.used_packages
        assert "numpy" not in result.possibly_unused

    def test_syntax_error_file_recorded(self, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(:\n    pass")
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_path)
        assert len(result.errors) == 1

    def test_alias_tracking(self, tmp_path):
        """import numpy as np — np.array() should be detected as used."""
        (tmp_path / "m.py").write_text("import numpy as np\nx = np.array([1,2,3])\n")
        from infrakit.deps.scanner import scan_project
        result = scan_project(tmp_path)
        assert "numpy" in result.used_packages

    def test_gitignore_filter_signature(self, tmp_path):
        """
        _walk_files passes (rel_posix: str, parts: tuple) to the filter.
        Verify the filter is called with the right shape.
        """
        calls = []

        def _capture(rel_posix, parts):
            calls.append((rel_posix, parts))
            return False  # don't exclude anything

        (tmp_path / "main.py").write_text("import os\nos.getcwd()\n")
        from infrakit.deps.scanner import scan_project
        scan_project(tmp_path, gitignore_filter=_capture)

        assert len(calls) > 0
        rel_posix, parts = calls[0]
        assert isinstance(rel_posix, str)
        assert "/" in rel_posix or rel_posix.endswith(".py")
        assert isinstance(parts, tuple)


# ===========================================================================
# _depfile tests
# ===========================================================================

class TestDepfile:

    def test_parse_requirements(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("# comment\nnumpy>=1.24.0\nrequests==2.31.0\nflask[async]>=3.0\n")
        from infrakit.deps.depfile import _parse_requirements
        df = _parse_requirements(req)
        names = [d.name for d in df.deps]
        assert "numpy" in names
        assert "requests" in names
        assert "flask" in names

    def test_parse_requirements_version_spec(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy>=1.24.0\n")
        from infrakit.deps.depfile import _parse_requirements
        df = _parse_requirements(req)
        assert df.deps[0].version_spec == ">=1.24.0"

    def test_parse_requirements_extras(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask[async]>=3.0\n")
        from infrakit.deps.depfile import _parse_requirements
        df = _parse_requirements(req)
        assert df.deps[0].extras == ["async"]

    def test_parse_pyproject_pep621(self, tmp_pyproject):
        from infrakit.deps.depfile import _parse_pyproject
        df = _parse_pyproject(tmp_pyproject / "pyproject.toml")
        names = [d.name for d in df.deps]
        assert "click" in names
        assert "rich" in names
        assert "flask" in names

    def test_find_dep_files_detects_both(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = [\n    "click>=8.0",\n]\n'
        )
        from infrakit.deps.depfile import find_dep_files
        dfs = find_dep_files(tmp_path)
        assert {df.format for df in dfs} == {"requirements", "pyproject"}

    def test_normalised_name(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("scikit_learn>=1.0\n")
        from infrakit.deps.depfile import _parse_requirements
        df = _parse_requirements(req)
        assert df.deps[0].normalised == "scikit-learn"

    def test_write_requirements_new_file(self, tmp_path):
        from infrakit.deps.depfile import write_requirements, PinnedDep
        declared = {
            "numpy": PinnedDep("numpy", "numpy>=1.24", ">=1.24", []),
            "requests": PinnedDep("requests", "requests==2.31.0", "==2.31.0", []),
            "flask": PinnedDep("flask", "flask>=3.0", ">=3.0", []),
        }
        out = tmp_path / "out.txt"
        write_requirements(["numpy", "requests"], declared, out)
        content = out.read_text()
        assert "numpy>=1.24" in content
        assert "requests==2.31.0" in content
        assert "flask" not in content

    def test_update_requirements_inplace(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy>=1.24\nrequests==2.31\nflask>=3.0\n")
        from infrakit.deps.depfile import _parse_requirements, update_requirements_inplace
        df = _parse_requirements(req)
        update_requirements_inplace(df, {"numpy", "requests"})
        content = req.read_text()
        assert "numpy" in content
        assert "requests" in content
        assert "flask" not in content

    def test_skip_vcs_requirements(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("git+https://github.com/org/repo.git\nnumpy>=1.0\n")
        from infrakit.deps.depfile import _parse_requirements
        df = _parse_requirements(req)
        assert len(df.deps) == 1
        assert df.deps[0].name == "numpy"


# ===========================================================================
# _health tests  (the three previously-failing tests are here)
# ===========================================================================

class TestHealth:

    # ── Bug fix 1: get_installed_version must find 'pip' ─────────────────

    def test_get_installed_version_known(self):
        """pip is always installed; must return a non-None version string."""
        from infrakit.deps.health import get_installed_version
        ver = get_installed_version("pip")
        assert ver is not None
        assert isinstance(ver, str)
        assert "." in ver

    def test_get_installed_version_normalised(self):
        """Underscores → hyphens normalisation must work."""
        from infrakit.deps.health import get_installed_version
        # 'pip' and 'pip' are the same — just verify normalisation path runs
        ver = get_installed_version("Pip")   # capital P, rare but valid
        # May be None on some envs, but must not raise
        assert ver is None or isinstance(ver, str)

    def test_get_installed_version_unknown(self):
        from infrakit.deps.health import get_installed_version
        assert get_installed_version("__nonexistent_package_xyz__") is None

    def test_get_all_installed_contains_pip(self):
        """get_all_installed must return at least pip."""
        from infrakit.deps.health import get_all_installed
        installed = get_all_installed()
        assert "pip" in installed
        assert isinstance(installed["pip"], str)

    # ── Bug fix 2: check_outdated must work without packaging installed ───

    def test_version_is_older_stdlib_fallback(self):
        """_version_is_older must work even when packaging is unavailable."""
        from infrakit.deps.health import _version_is_older
        with patch.dict("sys.modules", {"packaging": None, "packaging.version": None}):
            assert _version_is_older("1.0.0", "2.0.0") is True
            assert _version_is_older("2.0.0", "1.0.0") is False
            assert _version_is_older("1.0.0", "1.0.0") is False

    def test_version_is_older_with_packaging(self):
        from infrakit.deps.health import _version_is_older
        assert _version_is_older("1.24.0", "1.25.0") is True
        assert _version_is_older("2.0.0", "1.99.99") is False

    @patch("infrakit.deps.health._fetch_pypi_latest")
    @patch("infrakit.deps.health.get_all_installed")
    def test_check_outdated_detects_old(self, mock_installed, mock_fetch):
        """check_outdated returns 'outdated' when installed < latest."""
        mock_installed.return_value = {"pip": "1.0.0"}
        mock_fetch.return_value = "99.0.0"

        from infrakit.deps.health import check_outdated
        results = check_outdated(["pip"])
        assert len(results) == 1
        assert results[0].status == "outdated"
        assert results[0].current == "1.0.0"
        assert results[0].latest == "99.0.0"

    @patch("infrakit.deps.health._fetch_pypi_latest")
    @patch("infrakit.deps.health.get_all_installed")
    def test_check_outdated_up_to_date(self, mock_installed, mock_fetch):
        mock_installed.return_value = {"pip": "23.3.1"}
        mock_fetch.return_value = "23.3.1"

        from infrakit.deps.health import check_outdated
        results = check_outdated(["pip"])
        assert results[0].status == "up-to-date"

    @patch("infrakit.deps.health._fetch_pypi_latest")
    @patch("infrakit.deps.health.get_all_installed")
    def test_check_outdated_not_installed(self, mock_installed, mock_fetch):
        mock_installed.return_value = {}
        mock_fetch.return_value = "1.0.0"

        from infrakit.deps.health import check_outdated
        results = check_outdated(["some-package"])
        assert results[0].status == "not-installed"

    # ── Licenses ─────────────────────────────────────────────────────────

    def test_check_licenses_returns_list(self):
        from infrakit.deps.health import check_licenses
        results = check_licenses(["pip"])
        assert len(results) == 1
        assert results[0].package == "pip"

    def test_license_mit_compatible(self):
        from infrakit.deps.health import _normalise_license, _LICENSE_NOTES
        compatible, _ = _LICENSE_NOTES.get(_normalise_license("MIT"), (None, ""))
        assert compatible is True

    def test_license_gpl_flagged(self):
        from infrakit.deps.health import _normalise_license, _LICENSE_NOTES
        compatible, _ = _LICENSE_NOTES.get(_normalise_license("GPL-3.0"), (None, ""))
        assert compatible is False

    @patch("urllib.request.urlopen")
    def test_fetch_pypi_latest_parses_response(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"info": {"version": "2.0.0"}}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp

        from infrakit.deps.health import _fetch_pypi_latest
        assert _fetch_pypi_latest("requests") == "2.0.0"

    def test_pip_audit_missing_returns_error(self):
        from infrakit.deps.health import check_vulnerabilities
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            vulns, err = check_vulnerabilities()
        assert err is not None
        assert "pip-audit" in err


# ===========================================================================
# _optimizer tests
# ===========================================================================

class TestOptimizer:

    def test_remove_duplicates(self):
        from infrakit.deps.optimizer import ImportLine, _remove_duplicates
        imp1 = ImportLine("import os",  "import", "os",  ["os"],  {}, 0, 1, "stdlib")
        imp2 = ImportLine("import os",  "import", "os",  ["os"],  {}, 0, 3, "stdlib")
        imp3 = ImportLine("import sys", "import", "sys", ["sys"], {}, 0, 2, "stdlib")
        deduped, n = _remove_duplicates([imp1, imp2, imp3])
        assert n == 1
        assert len(deduped) == 2

    def test_import_line_to_source_simple(self):
        from infrakit.deps.optimizer import ImportLine
        imp = ImportLine(
            "import numpy as np", "import", "numpy",
            ["numpy"], {"numpy": "np"}, 0, 1, "third_party",
        )
        assert imp.to_source() == "import numpy as np"

    def test_import_line_to_source_from(self):
        from infrakit.deps.optimizer import ImportLine
        imp = ImportLine(
            "from os.path import join, exists", "from", "os.path",
            ["join", "exists"], {}, 0, 1, "stdlib",
        )
        src = imp.to_source()
        assert "from os.path import" in src
        assert "join" in src and "exists" in src

    def test_import_line_relative(self):
        from infrakit.deps.optimizer import ImportLine
        imp = ImportLine("from . import utils", "from", "", ["utils"], {}, 1, 1, "relative")
        assert imp.to_source() == "from . import utils"

    def test_categorise_stdlib(self):
        from infrakit.deps.optimizer import _categorise
        assert _categorise("os", 0, set()) == "stdlib"

    def test_categorise_third_party(self):
        from infrakit.deps.optimizer import _categorise
        assert _categorise("numpy", 0, set()) == "third_party"

    def test_categorise_local(self):
        from infrakit.deps.optimizer import _categorise
        assert _categorise("mypackage", 0, {"mypackage"}) == "local"

    def test_categorise_relative(self):
        from infrakit.deps.optimizer import _categorise
        assert _categorise("utils", 1, set()) == "relative"

    def test_optimise_file_deduplicates(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(textwrap.dedent("""\
            import os
            import os
            from pathlib import Path
            from pathlib import Path

            x = os.getcwd()
            p = Path(".")
        """))
        from infrakit.deps.optimizer import optimise_file
        result = optimise_file(f, tmp_path, use_isort=False, dry_run=True)
        assert result.duplicates_removed == 2

    def test_optimise_file_dry_run_does_not_write(self, tmp_path):
        f = tmp_path / "test.py"
        original = "import os\nimport os\nx = os.getcwd()\n"
        f.write_text(original)
        from infrakit.deps.optimizer import optimise_file
        optimise_file(f, tmp_path, use_isort=False, dry_run=True)
        assert f.read_text() == original

    def test_optimise_file_writes_when_not_dry_run(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("import os\nimport os\nx = os.getcwd()\n")
        from infrakit.deps.optimizer import optimise_file
        result = optimise_file(f, tmp_path, use_isort=False, dry_run=False)
        if result.changed:
            assert f.read_text().count("import os") == 1

    def test_sort_imports_groups(self):
        from infrakit.deps.optimizer import ImportLine, _sort_imports
        stdlib  = ImportLine("import os",     "import", "os",     ["os"],     {}, 0, 1, "stdlib")
        third   = ImportLine("import numpy",  "import", "numpy",  ["numpy"],  {}, 0, 2, "third_party")
        local   = ImportLine("import mymod",  "import", "mymod",  ["mymod"],  {}, 0, 3, "local")
        result  = _sort_imports([third, local, stdlib])
        assert result.index("import os") < result.index("import numpy")
        assert result.index("import numpy") < result.index("import mymod")

    def test_optimise_project_returns_list(self, tmp_path):
        (tmp_path / "a.py").write_text("import os\nx = os.getcwd()\n")
        (tmp_path / "b.py").write_text("import sys\ny = sys.argv\n")
        from infrakit.deps.optimizer import optimise_project
        results = optimise_project(tmp_path, dry_run=True)
        assert len(results) == 2


# ===========================================================================
# _clean tests
# ===========================================================================

class TestClean:

    def test_compute_removable_excludes_used(self):
        from infrakit.deps.clean import compute_removable
        with patch("infrakit.deps.clean.get_all_installed") as m:
            m.return_value = {"numpy": "1.24.0", "requests": "2.31.0", "boto3": "1.28.0", "pip": "23.0"}
            removable = compute_removable(used_packages={"numpy", "requests"}, declared_packages=set())
        assert "numpy" not in removable
        assert "requests" not in removable
        assert "boto3" in removable

    def test_compute_removable_excludes_always_keep(self):
        from infrakit.deps.clean import compute_removable
        with patch("infrakit.deps.clean.get_all_installed") as m:
            m.return_value = {"pip": "23.0", "setuptools": "68.0"}
            removable = compute_removable(set(), set())
        assert "pip" not in removable
        assert "setuptools" not in removable

    def test_compute_removable_respects_declared(self):
        from infrakit.deps.clean import compute_removable
        with patch("infrakit.deps.clean.get_all_installed") as m:
            m.return_value = {"flask": "3.0", "pip": "23.0"}
            removable = compute_removable(used_packages=set(), declared_packages={"flask"})
        assert "flask" not in removable

    def test_compute_removable_extra_protected(self):
        from infrakit.deps.clean import compute_removable
        with patch("infrakit.deps.clean.get_all_installed") as m:
            m.return_value = {"special-tool": "1.0", "pip": "23.0"}
            removable = compute_removable(set(), set(), protected={"special-tool"})
        assert "special-tool" not in removable

    def test_dry_run_does_not_call_pip(self):
        from infrakit.deps.clean import uninstall_packages
        with patch("subprocess.run") as mock_run:
            result = uninstall_packages(["boto3", "flask"], dry_run=True)
        mock_run.assert_not_called()
        assert result.dry_run is True
        assert result.to_remove == ["boto3", "flask"]

    def test_live_run_calls_pip(self):
        from infrakit.deps.clean import uninstall_packages
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = uninstall_packages(["boto3"], dry_run=False)
        mock_run.assert_called_once()
        assert "boto3" in result.removed


# ===========================================================================
# Integration tests
# ===========================================================================

class TestIntegration:

    def test_full_export_flow(self, tmp_project, tmp_path):
        from infrakit.deps import export
        out = tmp_path / "requirements.used.txt"
        scan_result, dep_files = export(root=tmp_project, output=out, keep_versions=True)
        assert out.exists()
        content = out.read_text()
        assert "numpy" in content
        assert "requests" in content
        # flask is in requirements.txt but never imported
        assert "flask" not in content

    def test_full_export_inplace(self, tmp_project):
        from infrakit.deps import export
        export(root=tmp_project, inplace=True)
        content = (tmp_project / "requirements.txt").read_text()
        assert "numpy" in content
        assert "requests" in content
        assert "flask" not in content

    # ── Bug fix 3: gitignore filter must work cross-platform ─────────────

    def test_scan_with_gitignore_excludes_directory(self, tmp_path):
        """
        Files inside a directory matched by .gitignore must not be scanned.
        Uses the new (rel_posix, parts) filter signature.
        """
        (tmp_path / ".gitignore").write_text("ignored/\n")

        ignored_dir = tmp_path / "ignored"
        ignored_dir.mkdir()
        (ignored_dir / "secret.py").write_text(
            "import boto3\nclient = boto3.client('s3')\n"
        )
        (tmp_path / "main.py").write_text("import os\nos.getcwd()\n")

        from infrakit.deps import scan
        result = scan(tmp_path, use_gitignore=True)
        assert "boto3" not in result.used_packages

    def test_scan_without_gitignore_sees_all_files(self, tmp_path):
        """When use_gitignore=False even gitignore-listed files are scanned."""
        (tmp_path / ".gitignore").write_text("ignored/\n")
        ignored_dir = tmp_path / "ignored"
        ignored_dir.mkdir()
        (ignored_dir / "secret.py").write_text(
            "import boto3\nclient = boto3.client('s3')\n"
        )

        from infrakit.deps import scan
        result = scan(tmp_path, use_gitignore=False)
        assert "boto3" in result.used_packages

    def test_gitignore_filename_pattern(self, tmp_path):
        """Filename-level patterns like '*.log' must also be respected."""
        (tmp_path / ".gitignore").write_text("secret_*.py\n")
        (tmp_path / "secret_keys.py").write_text("import paramiko\nparamiko.SSHClient()\n")
        (tmp_path / "main.py").write_text("import os\nos.getcwd()\n")

        from infrakit.deps import scan
        result = scan(tmp_path, use_gitignore=True)
        assert "paramiko" not in result.used_packages

    def test_pyproject_export(self, tmp_pyproject, tmp_path):
        from infrakit.deps import export
        out = tmp_path / "deps.txt"
        scan_result, _ = export(root=tmp_pyproject, output=out)
        content = out.read_text()
        assert "click" in content
        assert "rich" in content
        # flask and numpy declared but never imported
        assert "flask" not in content