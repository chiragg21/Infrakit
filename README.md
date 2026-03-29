# Infrakit

Infrakit is a comprehensive, modular developer infrastructure toolkit for Python projects. It provides CLI utilities, rich project scaffolding, a robust multi-provider LLM client, dependency management, profiling, and core utilities for logging and configuration.

## Installation

Install via pip:

```bash
pip install infrakit
# or if using uv
uv pip install infrakit
```

The CLI is exposed as `infrakit` and conveniently aliased as `ik`.

## Key Features

### 1. Project Scaffolding (`ik init`)

Quickly bootstrap new Python projects with standardized layouts, ready-to-use boilerplate, and optional LLM integration. Existing files are safely skipped if you re-run over a directory.

```bash
ik init my-project -t basic
ik init my-fastapi-app -t backend -v 0.1.0
ik init my-ai-tool -t ai --include-llm
```

**Available Templates**:
- **`basic`**: Minimal template (src, utils, tests).
- **`backend`**: FastAPI service (app, routes, middleware, Dockerfile, docker-compose).
- **`cli_tool`**: Distributable CLI application using Typer.
- **`pipeline`**: Data pipeline / ETL template (extract, transform, load, enrich).
- **`ai`**: AI/ML project optimized for notebooks and pipelines.

### 2. Multi-provider LLM Client (`infrakit.llm`)

A unified LLM client interface supporting **OpenAI** and **Gemini**. Built natively for robust production use cases, particularly when navigating free-tier API quotas.

**Features:**
- Seamless key rotation and persistent storage tracking.
- Local rate limiting (RPM/TPM gates).
- Async and multi-threaded batch generation.
- Structured output parsing and schema validation using `pydantic.BaseModel`.

**Quick Start:**
```python
from infrakit.llm import LLMClient, Prompt

client = LLMClient(keys={"openai_keys": ["sk-..."], "gemini_keys": ["AIza..."]}, storage_dir="./logs")
response = client.generate(Prompt(user="What is the capital of France?"), provider="openai")
print(response.content)
```

**LLM CLI tools:**
Monitor and control limits right from the CLI.
- `ik llm status --storage-dir ./logs`
- `ik llm quota set --provider openai --key sk-abc --rpm 60 --storage-dir ./logs`

### 3. Dependency Management (`infrakit.deps`)

In-depth Python dependency tools available under `ik deps` (or programmatically via `infrakit.deps`) to clean, health-check, scan, and optimize dependencies.

**Features:**
- `scan(root)`: Scan your project for actual Python dependencies used in code.
- `export()`: Export used dependencies to update `requirements.txt` or `pyproject.toml` automatically.
- `check(packages)`: Run health, security, and outdated checks on packages.
- `clean()`: Find and remove unused packages from the virtual environment.
- `optimise()`: Optimize and format imports across the project (integrates with `isort`).

### 4. Code Profiling (`infrakit.time`)

Lightweight timing and execution profiling for your Python projects.

**CLI Usage:**
Profile any script instantly to detect performance bottlenecks.
```bash
ik time run script.py --max-functions 30 --min-time 1.0
```

**Decorator Usage:**
Track specific pipeline steps inside your code:
```python
from infrakit.time import pipeline_profiler, track

@pipeline_profiler("Data Processing Pipeline")
def main():
    load_data()
    transform_data()

@track(name="Load Step")
def load_data(): pass
```

### 5. Core Utilities (`infrakit.core`)

Convenient implementations for common application needs.

- **Config Loader** (`infrakit.core.config.loader`): Multi-format configuration loader supporting JSON, YAML, INI, and `.env`. Automatically resolves variables using `python-dotenv` and converts types properly natively.
- **Logger** (`infrakit.core.logger`): Unified logging setups for consistent output across applications.
```python
from infrakit.core.logger import setup, get_logger

setup(level="INFO", strategy="date_level", stream="stdout")
log = get_logger(__name__)
log.info("Ready")
```
