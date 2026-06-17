# Infrakit

A modular developer toolkit for Python — project scaffolding, logging, config loading, a multi-provider LLM client, and dependency utilities.

**Requires Python 3.10+**

---

## Architecture

```
infrakit/
  core/config/   load · validate · convert · export      (env · yaml · json · ini)
  core/logger/   setup · get_logger                       (rotation · retention · json/human)
  llm/           LLMClient -- OpenAI + Gemini · key rotation · quota tracking ·
                 Pydantic structured output · async / threaded batch generation
  deps/          scan · export · check · clean · optimise (declared-vs-actual imports,
                 security / license / outdated checks)
  scaffolder/    init templates: basic · backend · ai · pipeline · cli_tool
  time/          pipeline_profiler · track                (step-level latency)
  cli            `infrakit` / `ik` -- thin wrapper over every subpackage
```

Each subpackage is independent and optional — install the core, or add `[llm]` / `[all]` extras as needed.

---

## Features

- **Scaffolding** — bootstrap a project from 5 templates (`basic`, `backend`, `ai`, `pipeline`, `cli_tool`), each with a pre-wired config file.
- **Config** — load `.env` / YAML / JSON / INI with `${VAR}` interpolation and type casting; validate via Pydantic or a lightweight `Schema`; convert between formats and export sanitized samples.
- **Logging** — one-call `setup()` with date/size rotation, retention, session-scoped filenames, and human or JSON output.
- **LLM client** — OpenAI + Gemini with key rotation, rate limiting, **quota tracking persisted across restarts**, **Pydantic structured output** (with schema retries), and async / threaded **batch** generation.
- **Dependency tools** — scan actually-imported packages, sync `pyproject.toml` / `requirements.txt`, check outdated / security / licenses, find unused installed packages, and optimise imports.
- **Profiling** — pipeline-level and step-level latency instrumentation via decorators.
- **CLI** — every subpackage is exposed through `infrakit` / `ik`.

---

## Installation

**Core** — scaffolding, config, logging, deps, profiling, and CLI:

```bash
pip install python-infrakit-dev
```

**With LLM support** — adds OpenAI and Gemini providers:

```bash
pip install python-infrakit-dev[llm]
```

**Everything:**

```bash
pip install python-infrakit-dev[all]
```

The CLI is available as both `infrakit` and `ik`.

---

## Quick Imports

Most public symbols are available directly from the top-level package:

```python
# Logging
from infrakit import setup, get_logger

# Config
from infrakit import load, load_env, validate, Schema, field

# Config conversion / export
from infrakit import convert_file, convert_dict, export_file, export_dict

# LLM (requires infrakit[llm])
from infrakit import LLMClient, Prompt, QuotaConfig

# Subpackages
from infrakit import deps, scaffolder, time
```

Or import from the specific subpackages:

```python
from infrakit.core.config import load, validate, convert_dict, export_file
from infrakit.core.logger import setup, get_logger
from infrakit.llm import LLMClient, Prompt
from infrakit.deps import scan, export, check, clean, optimise
from infrakit.scaffolder import scaffold_basic, scaffold_ai, scaffold_backend
from infrakit.time import pipeline_profiler, track
```

---

## Scaffolding

Bootstrap a new project in one command:

```bash
ik init my-project              # basic layout
ik init my-api -t backend       # FastAPI service
ik init my-model -t ai          # AI/ML project with pipelines and notebooks
ik init my-etl -t pipeline      # ETL/data pipeline
ik init my-cli -t cli_tool      # distributable CLI app
```

**All flags:**

| Flag | Values | Default | Description |
|---|---|---|---|
| `-t` / `--template` | `basic`, `backend`, `ai`, `pipeline`, `cli_tool` | `basic` | Project template |
| `-v` / `--version` | e.g. `0.1.0` | `0.1.0` | Starting version string |
| `--description` | string | `""` | Short description added to pyproject.toml and README |
| `--author` | string | `""` | Author line in pyproject.toml |
| `--config` | `env`, `yaml`, `json` | `env` | Config file format to generate |
| `--deps` | `toml`, `requirements` | `toml` | Dependency file style |
| `--include-llm` | flag | off | Add `utils/llm.py` wired to `infrakit.llm` |

Every template generates a config file pre-populated with the variables its utilities need (logger settings, LLM keys, app settings). Re-running over an existing directory skips files already present.

---

## Core — Config & Logger

### Config loader

```python
from infrakit.core.config import load, load_env

cfg = load_env(".env", cast_values=True)   # "true" → bool, "42" → int
cfg = load("config.yaml")
cfg = load("config.json")

port = cfg.get("APP_PORT", 8000)
```

**`load(path, *, ...)`** — load a config file (JSON, YAML, INI, or `.env`), format inferred from extension.

| Parameter | Default | Description |
|---|---|---|
| `path` | — | Path to the config file |
| `env_override` | `False` | Let existing environment variables override file values |
| `env_file` | `".env"` | `.env` file to merge in alongside the config |
| `inject_new` | `False` | Add any new keys from the env file into the result |
| `interpolate` | `True` | Expand `${VAR}` references within values |
| `cast_values` | `True` | Convert strings to int, float, bool where possible |

**`load_env(path, *, cast_values)`** — convenience wrapper to load a `.env` file directly. `cast_values` defaults to `False`.

---

### Config validation

```python
from infrakit.core.config import validate, Schema, field
from pydantic import BaseModel

# Pydantic model
class AppConfig(BaseModel):
    host: str
    port: int
    debug: bool = False

result = validate({"host": "localhost", "port": 8080}, AppConfig)
if result.ok:
    cfg = result.data   # fully typed AppConfig instance

# Lightweight dict schema (no Pydantic model needed)
schema = Schema({
    "host": field(str, required=True),
    "port": field(int, required=True),
    "debug": field(bool, required=False, default=False),
})
result = schema.validate({"host": "localhost", "port": 8080})
```

---

### Config conversion and export

```python
from infrakit.core.config import convert_file, convert_dict, export_file, export_dict

# Convert between formats
convert_file("config.yaml", "config.ini")
output, warnings = convert_dict(data, from_format="yaml", to_format="env")

# Sanitize config for sharing (replaces all values with YOUR_VALUE_HERE)
export_file("config.yaml", ".env.example", to_format="env")
safe = export_dict({"PORT": 8080, "SECRET": "abc"}, to_format="env")
```

---

### Logger

```python
from infrakit.core.logger import setup, get_logger

setup(log_dir="logs", strategy="date", stream="stdout", fmt="human", level="INFO")

log = get_logger(__name__)
log.info("started on port %d", 8080)
```

**`setup(*, ...)`** — configure logging once at startup. All parameters are keyword-only.

| Parameter | Default | Description |
|---|---|---|
| `level` | `"DEBUG"` | Minimum log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `fmt` | `"human"` | Console format — `"human"` for readable text, `"json"` for structured |
| `file_fmt` | `"human"` | Format used in log files (same options as `fmt`) |
| `strategy` | `"date"` | File rotation strategy — `"date"`, `"date_level"`, or `"single"` |
| `stream` | `"stdout"` | Where to echo logs — `"stdout"`, `"stderr"`, or `None` to disable |
| `log_dir` | `"logs"` | Directory where log files are written |
| `session` | `None` | Label this run — adds a session prefix to log filenames |
| `retention` | `30` | Days to keep old log files before deletion |
| `max_bytes` | `10MB` | Max size of a single log file before rotation |
| `force` | `False` | Re-apply setup even if already configured |

**`get_logger(name)`** — returns a stdlib `Logger`. Always call as `get_logger(__name__)`. Safe to call before `setup()`.

---

## LLM Client

> Requires `pip install python-infrakit-dev[llm]`

A unified client for **OpenAI** and **Gemini** with key rotation, rate limiting, quota tracking, and async/batch generation.

```python
from infrakit.llm import LLMClient, Prompt

client = LLMClient(
    keys={"openai_keys": ["sk-..."], "gemini_keys": ["AIza..."]},
    storage_dir="./llm_state",  # persists key usage across restarts
)

response = client.generate(Prompt(user="What is 2+2?"), provider="openai")
print(response.content)
```

**`LLMClient(keys, ...)`**

| Parameter | Default | Description |
|---|---|---|
| `keys` | — | Dict with `openai_keys` and/or `gemini_keys` lists of API key strings |
| `storage_dir` | `~/.infrakit/llm` | Directory where key state is persisted across restarts |
| `quota_file` | `None` | Path to a `quotas.json` file with per-provider/model limits |
| `mode` | `"async"` | Batch execution mode — `"async"` or `"threaded"` |
| `max_concurrent` | `3` | Max parallel requests in batch calls |
| `key_retries` | `3` | How many keys to try before giving up on a request |
| `schema_retries` | `2` | How many times to retry structured output parsing on schema mismatch |
| `meta_window` | `200` | Number of recent requests to keep in memory per key |
| `openai_model` | `"gpt-4o-mini"` | Default OpenAI model |
| `gemini_model` | `"gemini-2.0-flash"` | Default Gemini model |
| `show_progress` | `True` | Show a progress bar during batch generation |

---

**`generate(prompt, provider, response_model, **kwargs)`** — blocking single call, safe in any context.

**`async_generate(prompt, provider, response_model, **kwargs)`** — async version, use inside `async` functions.

| Parameter | Default | Description |
|---|---|---|
| `prompt` | — | `Prompt(system=..., user=...)` — `system` is optional |
| `provider` | — | `"openai"` or `"gemini"` |
| `response_model` | `None` | Pydantic `BaseModel` subclass for structured output parsing |

---

**`batch_generate(prompts, provider, ...)`** — run many prompts; results match input order.

**`async_batch_generate(prompts, provider, ...)`** — async version for use inside `async` functions.

| Parameter | Default | Description |
|---|---|---|
| `prompts` | — | List of `Prompt` objects |
| `provider` | — | `"openai"` or `"gemini"` |
| `response_model` | `None` | Pydantic model for structured output on every item |
| `max_concurrent` | client default | Override the client-level concurrency limit for this batch |
| `show_progress` | client default | Override the client-level progress bar setting |

```python
batch = client.batch_generate(prompts, provider="openai")
print(batch.success_count, batch.failure_count, batch.total_tokens)
for r in batch.results:
    print(r.content if not r.error else r.error)
```

---

**Structured output:**

```python
from pydantic import BaseModel

class Summary(BaseModel):
    title: str
    bullets: list[str]

response = client.generate(Prompt(user="Summarise: ..."), provider="openai", response_model=Summary)
if response.schema_matched:
    print(response.parsed.bullets)   # typed Summary instance
```

---

**`set_quota(provider, key_id, quota)`** — set limits for a specific key.

```python
from infrakit.llm import QuotaConfig

# key-level RPM (applies to all models on this key)
client.set_quota(provider="openai", key_id="sk-key1", quota=QuotaConfig(rpm_limit=60))

# per-model daily token limit
client.set_quota(provider="gemini", key_id="AIza-key1", quota=QuotaConfig(model="gemini-2.5-pro", daily_token_limit=250_000))
```

`QuotaConfig` fields: `model` (None = all models on the key), `rpm_limit`, `daily_token_limit`, `tpm_limit`.

Quota defaults can also be set in a `quotas.json` file — pass the path via `quota_file=` in the constructor.

---

**`status(provider, key_id)`** — return key status as a list of dicts. **`print_status(provider, key_id)`** — same but pretty-printed to stdout.

| Parameter | Default | Description |
|---|---|---|
| `provider` | `None` | Filter to `"openai"` or `"gemini"`; `None` returns all |
| `key_id` | `None` | Filter to a specific key (first 8 chars); `None` returns all |

```python
rows = client.status(provider="openai")
# each row: provider, key_id, status, rpm_limit, current_rpm, models
```

**CLI:**

```bash
ik llm status --storage-dir ./llm_state
ik llm quota set --provider openai --key sk-abc --rpm 60 --storage-dir ./llm_state
```

---

## Other Features

### Dependency management (`infrakit.deps`)

```bash
ik deps scan .                   # list packages your code actually imports
ik deps export . --format toml   # sync pyproject.toml / requirements.txt
ik deps check --packages numpy   # outdated, security, and license checks
ik deps clean . --dry-run        # find unused installed packages
ik deps optimise .               # sort and clean imports (isort)
```

**`scan(root, include_notebooks, use_gitignore)`**

| Parameter | Default | Description |
|---|---|---|
| `root` | — | Project root to scan |
| `include_notebooks` | `False` | Also scan `.ipynb` notebook files |
| `use_gitignore` | `True` | Skip paths matched by `.gitignore` |

**`export(root, output, inplace, keep_versions, include_notebooks, use_gitignore)`**

| Parameter | Default | Description |
|---|---|---|
| `root` | — | Project root to scan |
| `output` | `None` | Write to this path instead of the detected dependency file |
| `inplace` | `False` | Update the existing file in place |
| `keep_versions` | `True` | Preserve pinned version specifiers already in the file |
| `include_notebooks` | `False` | Also scan `.ipynb` files |
| `use_gitignore` | `True` | Skip gitignored paths |

**`check(root, packages, outdated, security, licenses)`**

| Parameter | Default | Description |
|---|---|---|
| `root` | `None` | Auto-scan this root for packages (used if `packages` is `None`) |
| `packages` | `None` | Explicit list of package names to check |
| `outdated` | `True` | Check for newer versions on PyPI |
| `security` | `True` | Run vulnerability checks |
| `licenses` | `True` | Check license compatibility |

Returns a `HealthReport` with `.outdated`, `.vulnerable`, `.licenses`, and `.errors` lists.

**`clean(root, protected, dry_run)`**

| Parameter | Default | Description |
|---|---|---|
| `root` | — | Project root (used to determine what is actually imported) |
| `protected` | `None` | Set of package names to never remove |
| `dry_run` | `True` | Preview only — pass `False` to actually uninstall |

Returns a `CleanResult` with `.to_remove`, `.removed`, `.skipped`, and `.errors` lists.

**`optimise(root, files, convert_to, use_isort, dry_run)`**

| Parameter | Default | Description |
|---|---|---|
| `root` | — | Project root |
| `files` | `None` | Specific files to process; `None` processes all `.py` files |
| `convert_to` | `None` | Rewrite import style (e.g. `"absolute"`) |
| `use_isort` | `True` | Run `isort` on each file |
| `dry_run` | `False` | Preview changes without writing files |

---

### Profiling (`infrakit.time`)

```bash
ik time run script.py
```

```python
from infrakit.time import pipeline_profiler, track

@pipeline_profiler("My Pipeline")
def main(): ...

@track(name="Load Step")
def load_data(): ...
```
