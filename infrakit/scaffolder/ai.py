"""
infrakit.scaffolder.templates.ai
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Scaffold an AI / ML project.

Layout
------
<project>/
├── src/
│   └── __init__.py
├── pipelines/          # data → feature → train → eval stages
│   └── __init__.py
├── data/
│   ├── raw/            # original, immutable data
│   ├── processed/      # cleaned / feature-engineered
│   └── outputs/        # model artefacts, predictions
├── notebooks/          # exploratory Jupyter notebooks
├── utils/
│   ├── __init__.py
│   ├── logger.py       # infrakit.logger boot (same pattern as basic)
│   └── llm.py          # infrakit.llm boot — ready-to-import LLMClient
├── prompts/            # .txt prompt templates kept out of code
│   └── default.txt
├── tests/
│   └── __init__.py
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
    _infrakit_dep,
    _pkg_dep,
    _logger_util,
    _src_init,
    _tests_init,
    _pyproject_toml,
    _requirements_txt,
)


# ── template content ──────────────────────────────────────────────────────────


def _llm_util(project_name: str) -> str:
    return f'''\
"""
utils.llm
~~~~~~~~~
Thin wrapper that boots the infrakit LLM client once and exports it.

Reads all configuration from the project config file (.env / config.yaml /
config.json) via infrakit.config — no raw os.getenv calls.

The client reads key state from ``~/.infrakit/llm/`` by default, and
loads quota limits from ``~/.infrakit/llm/quotas.json`` if that file
exists.  Both paths can be overridden via LLM_STATE_DIR / LLM_QUOTA_FILE.

Usage
-----
    from utils.llm import llm, Prompt

    response = llm.generate(Prompt(user="Summarise this text: ..."), provider="openai")
    print(response.content)

    # structured output
    from pydantic import BaseModel

    class Summary(BaseModel):
        title: str
        bullets: list[str]

    response = llm.generate(
        Prompt(system="Return only JSON.", user="Summarise: ..."),
        provider="openai",
        response_model=Summary,
    )
    if response.schema_matched:
        print(response.parsed.bullets)

    # async batch (inside an async function)
    batch = await llm.async_batch_generate(prompts, provider="gemini")
"""

import json
from pathlib import Path

from infrakit.core.config.loader import load, load_env
from infrakit.llm import LLMClient, Prompt  # re-export Prompt for convenience

# ── config loading ────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    if Path(".env").exists():
        return load_env(".env", cast_values=True)
    if Path("config.yaml").exists():
        return load("config.yaml")
    if Path("config.json").exists():
        return load("config.json")
    return {{}}


_cfg = _load_cfg()

# ── key loading ───────────────────────────────────────────────────────────────
# Keys are read from the project config or from a local keys.json file.
# Never commit real API keys — use .env or your secret manager.

def _load_keys() -> dict:
    keys_file = Path(_cfg.get("LLM_KEYS_FILE", "keys.json"))
    if keys_file.exists():
        with open(keys_file) as f:
            return json.load(f)

    # fall back to keys declared in the config file
    openai_key  = _cfg.get("OPENAI_API_KEY", "")
    gemini_key  = _cfg.get("GEMINI_API_KEY", "")
    groq_key    = _cfg.get("GROQ_API_KEY", "")
    return {{
        "openai_keys": [openai_key] if openai_key else [],
        "gemini_keys": [gemini_key] if gemini_key else [],
        "groq_keys":   [groq_key]   if groq_key   else [],
    }}


# ── client singleton ──────────────────────────────────────────────────────────

llm: LLMClient = LLMClient(
    keys=_load_keys(),
    # storage_dir and quota_file default to ~/.infrakit/llm/
    # override via LLM_STATE_DIR / LLM_QUOTA_FILE in your config file:
    storage_dir=_cfg.get("LLM_STATE_DIR") or None,
    quota_file=_cfg.get("LLM_QUOTA_FILE") or None,
    mode=_cfg.get("LLM_MODE", "async"),            # "async" | "threaded"
    max_concurrent=int(_cfg.get("LLM_CONCURRENCY", 3)),
    openai_model=_cfg.get("OPENAI_MODEL") or None,
    gemini_model=_cfg.get("GEMINI_MODEL") or None,
    groq_model=_cfg.get("GROQ_MODEL") or None,
)

__all__ = ["llm", "Prompt"]
'''


def _pipeline_init() -> str:
    return '''\
"""
pipelines
~~~~~~~~~
Each module in this package is a self-contained stage.

Typical order:
    ingest -> preprocess -> featurise -> train -> evaluate -> predict
"""
'''


def _pipeline_ingest() -> str:
    return '''\
"""
pipelines.ingest
~~~~~~~~~~~~~~~~
Load raw data from source(s) into data/raw/.
"""

from pathlib import Path

from utils.logger import get_logger

log = get_logger(__name__)
RAW_DIR = Path("data/raw")


def run() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    log.info("ingest: starting")
    # TODO: load your raw data here
    log.info("ingest: done")


if __name__ == "__main__":
    run()
'''


def _pipeline_preprocess() -> str:
    return '''\
"""
pipelines.preprocess
~~~~~~~~~~~~~~~~~~~~
Clean and normalise raw data; write to data/processed/.
"""

from pathlib import Path

from utils.logger import get_logger

log = get_logger(__name__)
RAW_DIR       = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def run() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    log.info("preprocess: starting")
    # TODO: read from RAW_DIR, clean, write to PROCESSED_DIR
    log.info("preprocess: done")


if __name__ == "__main__":
    run()
'''


def _pipeline_predict() -> str:
    return '''\
"""
pipelines.predict
~~~~~~~~~~~~~~~~~
Run inference and write outputs to data/outputs/.
"""

from pathlib import Path

from utils.llm import llm, Prompt
from utils.logger import get_logger

log = get_logger(__name__)
OUTPUT_DIR = Path("data/outputs")


def run(inputs: list[str], provider: str = "openai") -> list[str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("predict: %d inputs", len(inputs))

    prompts  = [Prompt(user=text) for text in inputs]
    batch    = llm.batch_generate(prompts, provider=provider)

    results  = []
    for i, r in enumerate(batch.results):
        if r.error:
            log.warning("predict: item %d failed — %s", i, r.error)
            results.append("")
        else:
            results.append(r.content)

    log.info(
        "predict: done — %d ok, %d failed, %d tokens",
        batch.success_count,
        batch.failure_count,
        batch.total_tokens,
    )
    return results


if __name__ == "__main__":
    sample = ["Summarise the history of Python in one sentence."]
    outputs = run(sample)
    for o in outputs:
        print(o)
'''


def _default_prompt() -> str:
    return """\
You are a helpful AI assistant working on the {project} project.
Answer concisely and accurately.
If you are unsure, say so rather than guessing.
"""


def _notebook_explore() -> str:
    # Minimal valid Jupyter notebook (JSON format)
    return '''{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": ["# Exploration\\n", "Initial data exploration notebook."]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import sys\\n",
    "sys.path.insert(0, \'..\')\\n",
    "\\n",
    "from utils.logger import get_logger\\n",
    "from utils.llm import llm, Prompt\\n",
    "\\n",
    "log = get_logger(__name__)\\n",
    "log.info(\'notebook ready\')"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
  "language_info": {"name": "python", "version": "3.10.0"}
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
'''


def _keys_json_template() -> str:
    return """\
{
  "_comment": "Fill in your API keys. Never commit this file — it is in .gitignore.",
  "openai_keys": [],
  "gemini_keys": [],
  "groq_keys":   []
}
"""


def _ai_gitignore() -> str:
    return _gitignore() + """\
# Data — keep raw data out of git
data/raw/
data/processed/
data/outputs/

# Model artefacts
*.pt
*.pth
*.ckpt
*.safetensors
*.onnx
*.pkl
*.joblib

# Notebooks checkpoints
.ipynb_checkpoints/

# Keys (never commit)
keys.json
.env
"""


def _ai_readme(project_name: str, description: str) -> str:
    title     = project_name.replace("-", " ").replace("_", " ").title()
    desc_line = f"\n{description}\n" if description else ""
    return f"""\
# {title}
{desc_line}
## Setup

```bash
pip install -e .
```

Copy and fill in your API keys:

```bash
cp keys.json.template keys.json
# edit keys.json
```

Optionally create `~/.infrakit/llm/quotas.json` to set per-model rate limits
(see `infrakit.llm` docs).

## Structure

| Path | Purpose |
|---|---|
| `src/` | Core library code |
| `pipelines/` | Data → feature → train → eval → predict stages |
| `data/raw/` | Original immutable data (not committed) |
| `data/processed/` | Cleaned data (not committed) |
| `data/outputs/` | Model outputs / predictions (not committed) |
| `notebooks/` | Exploratory Jupyter notebooks |
| `utils/llm.py` | LLM client singleton — import and use directly |
| `utils/logger.py` | Logger singleton |
| `prompts/` | Prompt templates (plain text, version-controlled) |

## Running a pipeline stage

```bash
python -m pipelines.ingest
python -m pipelines.preprocess
python -m pipelines.predict
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
"""


def _ai_pyproject(project_name: str, version: str, description: str, author: str) -> str:
    author_line = f'    "{author}",' if author else '    # "Your Name <you@example.com>",'
    infrakit_dep = _infrakit_dep()
    openai_dep   = _pkg_dep("openai")
    genai_dep    = _pkg_dep("google-genai")
    groq_dep     = _pkg_dep("groq")
    pydantic_dep = _pkg_dep("pydantic")
    tqdm_dep     = _pkg_dep("tqdm")
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
    {infrakit_dep},
    "{openai_dep}",
    "{genai_dep}",
    "{groq_dep}",
    "{pydantic_dep}",
    "{tqdm_dep}",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
    "jupyter",
    "ipykernel",
]
"""


# ── public API ────────────────────────────────────────────────────────────────


def scaffold_ai(
    project_dir: Path,
    *,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    config_fmt: str = "env",
    deps: str = "toml",
    include_notebooks: bool = True,
    include_llm: bool = True,
) -> ScaffoldResult:
    """
    Scaffold an AI / ML project layout under ``project_dir``.

    Parameters
    ----------
    project_dir:
        Root directory for the project (created if absent).
    version:
        Starting version string.
    description:
        Short project description.
    author:
        Author string.
    config_fmt:
        Config file format — ``"env"``, ``"yaml"``, or ``"json"``.
    deps:
        Dependency file style — ``"toml"`` or ``"requirements"``.
    include_notebooks:
        Whether to create the ``notebooks/`` directory with a starter notebook.
    """
    result       = ScaffoldResult(project_dir=project_dir)
    project_name = project_dir.name

    # ── directories ───────────────────────────────────────────────────────────
    _mkdir(result, project_dir)
    _mkdir(result, project_dir / "src")
    _mkdir(result, project_dir / "pipelines")
    _mkdir(result, project_dir / "data" / "raw")
    _mkdir(result, project_dir / "data" / "processed")
    _mkdir(result, project_dir / "data" / "outputs")
    _mkdir(result, project_dir / "utils")
    _mkdir(result, project_dir / "prompts")
    _mkdir(result, project_dir / "tests")
    _mkdir(result, project_dir / "logs")

    if include_notebooks:
        _mkdir(result, project_dir / "notebooks")

    # ── src ───────────────────────────────────────────────────────────────────
    _write(result, project_dir / "src" / "__init__.py", _src_init(version))

    # ── pipelines ─────────────────────────────────────────────────────────────
    _write(result, project_dir / "pipelines" / "__init__.py",  _pipeline_init())
    _write(result, project_dir / "pipelines" / "ingest.py",    _pipeline_ingest())
    _write(result, project_dir / "pipelines" / "preprocess.py", _pipeline_preprocess())
    _write(result, project_dir / "pipelines" / "predict.py",   _pipeline_predict())

    # ── prompts ───────────────────────────────────────────────────────────────
    _write(result, project_dir / "prompts" / "default.txt", _default_prompt())

    # ── utils ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "utils" / "__init__.py", '"""Shared utilities."""\n')
    _write(result, project_dir / "utils" / "logger.py",   _logger_util())
    if include_llm:
        _write(result, project_dir / "utils" / "llm.py",  _llm_util(project_name))

    # ── notebooks ─────────────────────────────────────────────────────────────
    if include_notebooks:
        _write(result, project_dir / "notebooks" / "01_explore.ipynb",
               _notebook_explore())

    # ── tests ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "tests" / "__init__.py", _tests_init())

    # ── config ────────────────────────────────────────────────────────────────
    cfg_name, cfg_content = _config_content(config_fmt, include_llm=include_llm)
    _write(result, project_dir / cfg_name, cfg_content)

    # ── keys template (safe placeholder — never contains real keys) ───────────
    _write(result, project_dir / "keys.json", _keys_json_template())

    # ── dependency file ───────────────────────────────────────────────────────
    if deps == "requirements":
        _write(result, project_dir / "requirements.txt",
               _requirements_txt(project_name))
    else:
        _write(result, project_dir / "pyproject.toml",
               _ai_pyproject(project_name, version, description, author))

    # ── repo files ────────────────────────────────────────────────────────────
    _write(result, project_dir / "README.md",    _ai_readme(project_name, description))
    _write(result, project_dir / ".gitignore",   _ai_gitignore())

    return result