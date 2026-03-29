"""
infrakit.scaffolder.templates.pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Scaffold a data pipeline / ETL project.

Designed for batch jobs that extract, transform, and load data —
with or without an LLM enrichment step.

Layout
------
<project>/
├── src/
│   └── __init__.py
├── pipeline/
│   ├── __init__.py
│   ├── extract.py      # pull from source(s)
│   ├── transform.py    # clean / reshape
│   ├── enrich.py       # optional LLM enrichment step
│   ├── load.py         # write to destination
│   └── runner.py       # orchestrator — runs the full DAG
├── schemas/
│   ├── __init__.py
│   └── records.py      # Pydantic models for input/output records
├── data/
│   ├── input/          # raw source files (not committed)
│   ├── staging/        # intermediate work (not committed)
│   └── output/         # final output (not committed)
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   └── llm.py          # optional
├── tests/
│   ├── __init__.py
│   └── test_pipeline.py
├── logs/
├── pyproject.toml / requirements.txt
├── config.{env|yaml|json}
├── README.md
└── .gitignore
"""

from __future__ import annotations

from pathlib import Path

from infrakit.scaffolder.generator import (
    ScaffoldResult,
    _mkdir,
    _write,
    _config_content,
    _gitignore,
    _logger_util,
    _src_init,
    _tests_init,
    _pyproject_toml,
    _requirements_txt,
)
from infrakit.scaffolder.ai import _llm_util


# ── template content ──────────────────────────────────────────────────────────


def _pipeline_pkg_init() -> str:
    return '''\
"""
pipeline
~~~~~~~~
Stages are independent modules; runner.py wires them in order.

Stage contract
--------------
Each stage exposes a ``run(**kwargs)`` function that:
  - Reads from a well-known location (data/input, data/staging, etc.)
  - Writes its output to the next location
  - Returns a summary dict  {records_in, records_out, errors}
  - Is idempotent where possible
"""
'''


def _extract() -> str:
    return '''\
"""
pipeline.extract
~~~~~~~~~~~~~~~~
Pull records from source(s) into data/input/.
"""

from pathlib import Path

from utils.logger import get_logger

log     = get_logger(__name__)
IN_DIR  = Path("data/input")


def run(source: str = "") -> dict:
    IN_DIR.mkdir(parents=True, exist_ok=True)
    log.info("extract: starting (source=%r)", source)

    records = []
    # TODO: fetch from API / database / files and append to `records`

    log.info("extract: %d records fetched", len(records))
    return {"records_in": 0, "records_out": len(records), "errors": 0}
'''


def _transform() -> str:
    return '''\
"""
pipeline.transform
~~~~~~~~~~~~~~~~~~
Clean and reshape records from data/input/ → data/staging/.
"""

from pathlib import Path

from utils.logger import get_logger

log         = get_logger(__name__)
IN_DIR      = Path("data/input")
STAGING_DIR = Path("data/staging")


def run() -> dict:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    log.info("transform: starting")

    errors = 0
    records_out = 0

    # TODO: read files from IN_DIR, clean/reshape, write to STAGING_DIR

    log.info("transform: %d records, %d errors", records_out, errors)
    return {"records_in": 0, "records_out": records_out, "errors": errors}
'''


def _enrich(include_llm: bool) -> str:
    if include_llm:
        return '''\
"""
pipeline.enrich
~~~~~~~~~~~~~~~
Optional LLM enrichment step — adds AI-generated fields to records.
Reads from data/staging/, writes enriched records back to data/staging/.
"""

from pathlib import Path

from utils.llm import llm, Prompt
from utils.logger import get_logger

log         = get_logger(__name__)
STAGING_DIR = Path("data/staging")


def run(provider: str = "openai", batch_size: int = 50) -> dict:
    log.info("enrich: starting (provider=%s)", provider)

    # TODO: load records from STAGING_DIR
    raw_texts: list[str] = []

    if not raw_texts:
        log.info("enrich: nothing to enrich")
        return {"records_in": 0, "records_out": 0, "errors": 0}

    prompts = [Prompt(user=text) for text in raw_texts]
    batch   = llm.batch_generate(prompts, provider=provider)

    errors = batch.failure_count
    log.info(
        "enrich: %d ok, %d errors, %d tokens",
        batch.success_count, errors, batch.total_tokens,
    )

    # TODO: merge batch.results back into records and write to STAGING_DIR

    return {
        "records_in":  len(raw_texts),
        "records_out": batch.success_count,
        "errors":      errors,
    }


if __name__ == "__main__":
    run()
'''
    else:
        return '''\
"""
pipeline.enrich
~~~~~~~~~~~~~~~
Placeholder enrichment step — add derived / computed fields to records.
Reads from data/staging/, writes back to data/staging/.
"""

from pathlib import Path

from utils.logger import get_logger

log         = get_logger(__name__)
STAGING_DIR = Path("data/staging")


def run() -> dict:
    log.info("enrich: starting")
    # TODO: load records, compute derived fields, write back
    return {"records_in": 0, "records_out": 0, "errors": 0}
'''


def _load() -> str:
    return '''\
"""
pipeline.load
~~~~~~~~~~~~~
Write staged records to the final destination (data/output/, DB, API …).
"""

from pathlib import Path

from utils.logger import get_logger

log        = get_logger(__name__)
STAGE_DIR  = Path("data/staging")
OUTPUT_DIR = Path("data/output")


def run(destination: str = "file") -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("load: starting (destination=%r)", destination)

    records_written = 0
    errors          = 0

    if destination == "file":
        # TODO: read from STAGE_DIR, write to OUTPUT_DIR
        pass
    else:
        # TODO: write to database / external API
        pass

    log.info("load: %d written, %d errors", records_written, errors)
    return {"records_in": 0, "records_out": records_written, "errors": errors}
'''


def _runner(include_llm: bool) -> str:
    enrich_import = "from pipeline import enrich\n" if True else ""
    enrich_call   = (
        "    summary['enrich'] = enrich.run(provider=provider)\n"
        if include_llm else
        "    summary['enrich'] = enrich.run()\n"
    )
    provider_param = (
        "    provider: str = \"openai\","
        if include_llm else ""
    )
    return f'''\
"""
pipeline.runner
~~~~~~~~~~~~~~~
Orchestrates the full extract → transform → enrich → load sequence.

Run the full pipeline:
    python -m pipeline.runner

Run individual stages:
    python -m pipeline.extract
    python -m pipeline.transform
    python -m pipeline.enrich
    python -m pipeline.load
"""

from pipeline import extract, transform, enrich, load
from utils.logger import get_logger

log = get_logger(__name__)


def run(
    source: str = "",
    destination: str = "file",
{("    provider: str = 'openai'," if include_llm else "")}
) -> dict:
    log.info("pipeline: start")
    summary = {{}}

    summary["extract"]   = extract.run(source=source)
    summary["transform"] = transform.run()
{enrich_call}    summary["load"]      = load.run(destination=destination)

    total_errors = sum(s.get("errors", 0) for s in summary.values())
    log.info("pipeline: done — %d total errors", total_errors)
    return summary


if __name__ == "__main__":
    import json, sys
    result = run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if all(s.get("errors", 0) == 0 for s in result.values()) else 1)
'''


def _schemas_records() -> str:
    return '''\
"""
schemas.records
~~~~~~~~~~~~~~~
Pydantic models for input and output records.

Define your data contracts here so every pipeline stage can import and
validate against them.
"""

from typing import Optional
from pydantic import BaseModel


class InputRecord(BaseModel):
    """Raw record as received from the source."""
    id: str
    raw_text: str


class OutputRecord(BaseModel):
    """Enriched / transformed record written to the destination."""
    id: str
    processed_text: str
    enriched_field: Optional[str] = None
'''


def _test_pipeline() -> str:
    return '''\
"""tests.test_pipeline — smoke tests for each stage."""

import pytest
from unittest.mock import patch


def test_extract_returns_summary():
    from pipeline import extract
    # patch out any I/O so the test stays offline
    result = extract.run(source="")
    assert "records_out" in result
    assert "errors" in result


def test_transform_returns_summary():
    from pipeline import transform
    result = transform.run()
    assert "records_out" in result


def test_load_returns_summary(tmp_path, monkeypatch):
    import pipeline.load as load_mod
    monkeypatch.setattr(load_mod, "OUTPUT_DIR", tmp_path / "output")
    result = load_mod.run(destination="file")
    assert "records_out" in result


def test_runner_returns_all_stages():
    from pipeline.runner import run
    result = run()
    assert set(result.keys()) >= {"extract", "transform", "enrich", "load"}
'''


def _pipeline_pyproject(
    project_name: str, version: str, description: str, author: str, include_llm: bool
) -> str:
    author_line = f'    "{author}",' if author else '    # "Your Name <you@example.com>",'
    llm_deps = """\
    "openai",
    "google-generativeai",
    "tqdm",
""" if include_llm else ""
    return f"""\
[project]
name        = "{project_name}"
version     = "{version}"
description = "{description}"
readme      = "README.md"
requires-python = ">=3.10"
authors = [
{author_line}
]

dependencies = [
    "infrakit",
    "pydantic>=2.0",
{llm_deps}]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
]
"""


def _pipeline_readme(project_name: str, description: str, include_llm: bool) -> str:
    title     = project_name.replace("-", " ").replace("_", " ").title()
    desc_line = f"\n{description}\n" if description else ""
    llm_note  = (
        "\nIncludes an LLM enrichment step via `infrakit.llm`. "
        "Set `OPENAI_API_KEY` or `GEMINI_API_KEY` to enable it.\n"
    ) if include_llm else ""
    return f"""\
# {title}
{desc_line}{llm_note}
## Setup

```bash
pip install -e .
```

## Run

```bash
# full pipeline
python -m pipeline.runner

# individual stages
python -m pipeline.extract
python -m pipeline.transform
python -m pipeline.enrich
python -m pipeline.load
```

## Structure

| Path | Purpose |
|---|---|
| `pipeline/extract.py` | Pull records from source |
| `pipeline/transform.py` | Clean and reshape |
| `pipeline/enrich.py` | {"LLM enrichment" if include_llm else "Computed / derived fields"} |
| `pipeline/load.py` | Write to destination |
| `pipeline/runner.py` | Orchestrate all stages |
| `schemas/records.py` | Pydantic data contracts |
| `data/input/` | Raw source data (not committed) |
| `data/staging/` | Intermediate (not committed) |
| `data/output/` | Final output (not committed) |

## Development

```bash
pip install -e ".[dev]"
pytest
```
"""


def _pipeline_gitignore() -> str:
    return _gitignore() + """\
# Pipeline data (never commit raw / staging / output data)
data/input/
data/staging/
data/output/

# Keys
.env.local
keys.json
"""


# ── public API ────────────────────────────────────────────────────────────────


def scaffold_pipeline(
    project_dir: Path,
    *,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    config_fmt: str = "env",
    deps: str = "toml",
    include_llm: bool = False,
) -> ScaffoldResult:
    """
    Scaffold a data pipeline / ETL project under ``project_dir``.

    Parameters
    ----------
    project_dir:
        Root directory for the project.
    version:
        Starting version string.
    description:
        Short project description.
    author:
        Author string.
    config_fmt:
        Config file format — ``"env"``, ``"yaml"``, or ``"json"``.
    deps:
        ``"toml"`` or ``"requirements"``.
    include_llm:
        Whether to wire up an LLM enrichment step in the pipeline.
    """
    result       = ScaffoldResult(project_dir=project_dir)
    project_name = project_dir.name

    # ── directories ───────────────────────────────────────────────────────────
    _mkdir(result, project_dir)
    _mkdir(result, project_dir / "src")
    _mkdir(result, project_dir / "pipeline")
    _mkdir(result, project_dir / "schemas")
    _mkdir(result, project_dir / "data" / "input")
    _mkdir(result, project_dir / "data" / "staging")
    _mkdir(result, project_dir / "data" / "output")
    _mkdir(result, project_dir / "utils")
    _mkdir(result, project_dir / "tests")
    _mkdir(result, project_dir / "logs")

    # ── src ───────────────────────────────────────────────────────────────────
    _write(result, project_dir / "src" / "__init__.py", _src_init(version))

    # ── pipeline stages ───────────────────────────────────────────────────────
    _write(result, project_dir / "pipeline" / "__init__.py",  _pipeline_pkg_init())
    _write(result, project_dir / "pipeline" / "extract.py",   _extract())
    _write(result, project_dir / "pipeline" / "transform.py", _transform())
    _write(result, project_dir / "pipeline" / "enrich.py",    _enrich(include_llm))
    _write(result, project_dir / "pipeline" / "load.py",      _load())
    _write(result, project_dir / "pipeline" / "runner.py",    _runner(include_llm))

    # ── schemas ───────────────────────────────────────────────────────────────
    _write(result, project_dir / "schemas" / "__init__.py",   "")
    _write(result, project_dir / "schemas" / "records.py",    _schemas_records())

    # ── utils ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "utils" / "__init__.py", '"""Shared utilities."""\n')
    _write(result, project_dir / "utils" / "logger.py",   _logger_util())
    if include_llm:
        _write(result, project_dir / "utils" / "llm.py",  _llm_util(project_name))

    # ── tests ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "tests" / "__init__.py",     _tests_init())
    _write(result, project_dir / "tests" / "test_pipeline.py", _test_pipeline())

    # ── config ────────────────────────────────────────────────────────────────
    cfg_name, cfg_content = _config_content(config_fmt)
    _write(result, project_dir / cfg_name, cfg_content)

    # ── dependency file ───────────────────────────────────────────────────────
    if deps == "requirements":
        _write(result, project_dir / "requirements.txt",
               _requirements_txt(project_name))
    else:
        _write(result, project_dir / "pyproject.toml",
               _pipeline_pyproject(project_name, version, description, author, include_llm))

    # ── repo files ────────────────────────────────────────────────────────────
    _write(result, project_dir / "README.md",
           _pipeline_readme(project_name, description, include_llm))
    _write(result, project_dir / ".gitignore", _pipeline_gitignore())

    return result