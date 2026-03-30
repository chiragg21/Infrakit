"""
infrakit.scaffolder.templates.backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Scaffold a FastAPI backend service.

Layout
------
<project>/
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app factory + lifespan
│   ├── config.py           # Pydantic Settings — reads from env
│   ├── dependencies.py     # Shared FastAPI dependencies (db, auth, llm)
│   ├── routes/
│   │   ├── __init__.py
│   │   └── health.py       # GET /health — always included
│   ├── models/
│   │   ├── __init__.py
│   │   └── base.py         # SQLAlchemy / Pydantic base stubs
│   ├── services/
│   │   ├── __init__.py
│   │   └── llm_service.py  # thin service wrapper around utils.llm
│   └── middleware/
│       ├── __init__.py
│       └── logging.py      # request-level access log middleware
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   └── llm.py              # infrakit.llm singleton (optional)
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── logs/
├── Dockerfile
├── docker-compose.yml
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
    _gitignore,
    _logger_util,
    _src_init,
    _tests_init,
)


# ── template content ──────────────────────────────────────────────────────────


def _backend_env_config(project_name: str, include_llm: bool) -> str:
    llm_block = """\

# LLM
LLM_KEYS_FILE=keys.json
OPENAI_API_KEY=
GEMINI_API_KEY=
LLM_MODE=async
LLM_CONCURRENCY=3
# OPENAI_MODEL=gpt-4o
# GEMINI_MODEL=gemini-2.0-flash
""" if include_llm else ""
    return f"""\
# Application
APP_NAME={project_name}
APP_ENV=development
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8000

# Database
DATABASE_URL=sqlite:///./app.db

# Logger
LOG_DIR=logs
LOG_STRATEGY=date
LOG_STREAM=stdout
LOG_FORMAT=human
LOG_LEVEL=DEBUG
{llm_block}"""


def _backend_yaml_config(project_name: str, include_llm: bool) -> str:
    llm_block = """

# LLM
LLM_KEYS_FILE: keys.json
OPENAI_API_KEY: ""
GEMINI_API_KEY: ""
LLM_MODE: async
LLM_CONCURRENCY: 3
# OPENAI_MODEL: gpt-4o
# GEMINI_MODEL: gemini-2.0-flash
""" if include_llm else ""
    return f"""\
# Application configuration
app:
  name: {project_name}
  env: development
  debug: false
  host: 0.0.0.0
  port: 8000

# Database
DATABASE_URL: sqlite:///./app.db

# Logger (flat keys — read by utils/logger.py via infrakit.config)
LOG_DIR: logs
LOG_STRATEGY: date
LOG_STREAM: stdout
LOG_FORMAT: human
LOG_LEVEL: DEBUG
{llm_block}"""


def _backend_json_config(project_name: str, include_llm: bool) -> str:
    llm_keys = """,
  "LLM_KEYS_FILE": "keys.json",
  "OPENAI_API_KEY": "",
  "GEMINI_API_KEY": "",
  "LLM_MODE": "async",
  "LLM_CONCURRENCY": 3""" if include_llm else ""
    return f"""\
{{
  "app": {{
    "name": "{project_name}",
    "env": "development",
    "debug": false,
    "host": "0.0.0.0",
    "port": 8000
  }},
  "DATABASE_URL": "sqlite:///./app.db",
  "LOG_DIR": "logs",
  "LOG_STRATEGY": "date",
  "LOG_STREAM": "stdout",
  "LOG_FORMAT": "human",
  "LOG_LEVEL": "DEBUG"{llm_keys}
}}
"""


def _backend_config_content(
    fmt: str, project_name: str, include_llm: bool
) -> tuple[str, str]:
    if fmt == "yaml":
        return "config.yaml", _backend_yaml_config(project_name, include_llm)
    if fmt == "json":
        return "config.json", _backend_json_config(project_name, include_llm)
    return ".env", _backend_env_config(project_name, include_llm)


def _app_init(version: str) -> str:
    return f'__version__ = "{version}"\n'


def _app_config(project_name: str) -> str:
    return f'''\
"""
app.config
~~~~~~~~~~
All configuration is read from environment variables (12-factor style).

Usage
-----
    from app.config import settings

    print(settings.app_env)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # application
    app_name: str    = "{project_name}"
    app_env:  str    = "development"
    app_debug: bool  = False
    app_host: str    = "0.0.0.0"
    app_port: int    = 8000

    # optional: database
    database_url: str = "sqlite:///./app.db"

    # optional: LLM keys (override ~/.infrakit/llm/ defaults)
    openai_api_key: str  = ""
    gemini_api_key: str  = ""
    llm_mode: str        = "async"
    llm_concurrency: int = 3


settings = Settings()
'''


def _app_main(project_name: str) -> str:
    title = project_name.replace("-", " ").replace("_", " ").title()
    return f'''\
"""
app.main
~~~~~~~~
FastAPI application factory.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware.logging import AccessLogMiddleware
from app.routes import health
from utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup: {project_name}")
    yield
    log.info("shutdown: {project_name}")


def create_app() -> FastAPI:
    app = FastAPI(
        title="{title}",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AccessLogMiddleware)

    app.include_router(health.router)

    return app


app = create_app()
'''


def _app_dependencies() -> str:
    return '''\
"""
app.dependencies
~~~~~~~~~~~~~~~~
Shared FastAPI dependency-injection helpers.
"""

from fastapi import Header, HTTPException


async def get_api_key(x_api_key: str = Header(...)) -> str:
    """Placeholder API-key auth dependency."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    return x_api_key
'''


def _route_health() -> str:
    return '''\
"""
app.routes.health
~~~~~~~~~~~~~~~~~
GET /health — liveness probe.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from app import __version__
    return HealthResponse(status="ok", version=__version__)
'''


def _models_base() -> str:
    return '''\
"""
app.models.base
~~~~~~~~~~~~~~~
Shared base classes for ORM models and Pydantic schemas.
"""

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    """Base class for all API request/response schemas."""
    model_config = ConfigDict(from_attributes=True)
'''


def _services_llm() -> str:
    return '''\
"""
app.services.llm_service
~~~~~~~~~~~~~~~~~~~~~~~~~
Thin async service wrapper around the infrakit LLM client.

Keeps route handlers clean — they call this service, never the LLM client directly.
"""

from pydantic import BaseModel
from typing import Optional, Type

from utils.llm import llm, Prompt
from utils.logger import get_logger

log = get_logger(__name__)


async def generate(
    user: str,
    *,
    system: Optional[str] = None,
    provider: str = "openai",
    response_model: Optional[Type[BaseModel]] = None,
):
    """
    Single-prompt async generate.

    Returns the LLMResponse — callers should check .error before using .content.
    """
    prompt = Prompt(user=user, system=system)
    response = await llm.async_generate(prompt, provider=provider,
                                        response_model=response_model)
    if response.error:
        log.warning("llm_service: error — %s", response.error)
    return response
'''


def _middleware_logging() -> str:
    return '''\
"""
app.middleware.logging
~~~~~~~~~~~~~~~~~~~~~~
Minimal access-log middleware — logs method, path, status, and latency.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from utils.logger import get_logger

log = get_logger("access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0       = time.perf_counter()
        response = await call_next(request)
        ms       = (time.perf_counter() - t0) * 1000
        log.info(
            "%s %s %d %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            ms,
        )
        return response
'''


def _test_health() -> str:
    return '''\
"""tests.test_health — basic liveness check."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
'''


def _dockerfile(project_name: str) -> str:
    return f"""\
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""


def _docker_compose(project_name: str) -> str:
    return f"""\
version: "3.9"

services:
  api:
    build: .
    container_name: {project_name}
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped
"""


def _backend_pyproject(
    project_name: str, version: str, description: str, author: str
) -> str:
    author_line = f'    "{author}",' if author else '    # "Your Name <you@example.com>",'
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
    "fastapi>=0.110",
    "uvicorn[standard]",
    "pydantic>=2.0",
    "pydantic-settings",
    "openai",
    "google-generativeai",
    "tqdm",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
    "httpx",         # required by TestClient
]

[project.scripts]
serve = "{project_name}.app.main:app"
"""


def _backend_readme(project_name: str, description: str) -> str:
    title     = project_name.replace("-", " ").replace("_", " ").title()
    desc_line = f"\n{description}\n" if description else ""
    return f"""\
# {title}
{desc_line}
## Setup

```bash
pip install -e .
cp .env .env   # fill in secrets
```

## Run

```bash
uvicorn app.main:app --reload
```

Or with Docker:

```bash
docker-compose up --build
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |

## Structure

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI app factory |
| `app/config.py` | Pydantic Settings (env-driven) |
| `app/routes/` | Route handlers |
| `app/models/` | ORM / schema models |
| `app/services/` | Business logic |
| `app/middleware/` | Request middleware |
| `utils/llm.py` | LLM client singleton |
| `utils/logger.py` | Logger singleton |

## Development

```bash
pip install -e ".[dev]"
pytest
```
"""


def _backend_gitignore() -> str:
    return _gitignore() + """\
# Docker
.dockerignore

# Database
*.db
*.sqlite3

# Keys
.env
keys.json
"""


# ── public API ────────────────────────────────────────────────────────────────


def scaffold_backend(
    project_dir: Path,
    *,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    config_fmt: str = "env",
    deps: str = "toml",
    include_llm: bool = True,
) -> ScaffoldResult:
    """
    Scaffold a FastAPI backend service under ``project_dir``.

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
        Whether to include ``utils/llm.py`` and ``app/services/llm_service.py``.
    """
    result       = ScaffoldResult(project_dir=project_dir)
    project_name = project_dir.name

    # ── directories ───────────────────────────────────────────────────────────
    _mkdir(result, project_dir)
    _mkdir(result, project_dir / "app")
    _mkdir(result, project_dir / "app" / "routes")
    _mkdir(result, project_dir / "app" / "models")
    _mkdir(result, project_dir / "app" / "services")
    _mkdir(result, project_dir / "app" / "middleware")
    _mkdir(result, project_dir / "utils")
    _mkdir(result, project_dir / "tests")
    _mkdir(result, project_dir / "logs")

    # ── app package ───────────────────────────────────────────────────────────
    _write(result, project_dir / "app" / "__init__.py",      _app_init(version))
    _write(result, project_dir / "app" / "main.py",          _app_main(project_name))
    _write(result, project_dir / "app" / "config.py",        _app_config(project_name))
    _write(result, project_dir / "app" / "dependencies.py",  _app_dependencies())

    # ── routes ────────────────────────────────────────────────────────────────
    _write(result, project_dir / "app" / "routes" / "__init__.py", "")
    _write(result, project_dir / "app" / "routes" / "health.py",   _route_health())

    # ── models ────────────────────────────────────────────────────────────────
    _write(result, project_dir / "app" / "models" / "__init__.py", "")
    _write(result, project_dir / "app" / "models" / "base.py",     _models_base())

    # ── services ──────────────────────────────────────────────────────────────
    _write(result, project_dir / "app" / "services" / "__init__.py", "")
    if include_llm:
        _write(result, project_dir / "app" / "services" / "llm_service.py",
               _services_llm())

    # ── middleware ────────────────────────────────────────────────────────────
    _write(result, project_dir / "app" / "middleware" / "__init__.py", "")
    _write(result, project_dir / "app" / "middleware" / "logging.py",
           _middleware_logging())

    # ── utils ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "utils" / "__init__.py", '"""Shared utilities."""\n')
    _write(result, project_dir / "utils" / "logger.py",   _logger_util())
    if include_llm:
        from infrakit.scaffolder.ai import _llm_util, _keys_json_template
        _write(result, project_dir / "utils" / "llm.py",  _llm_util(project_name))
        _write(result, project_dir / "keys.json",          _keys_json_template())

    # ── tests ─────────────────────────────────────────────────────────────────
    _write(result, project_dir / "tests" / "__init__.py", _tests_init())
    _write(result, project_dir / "tests" / "test_health.py", _test_health())

    # ── config ────────────────────────────────────────────────────────────────
    cfg_name, cfg_content = _backend_config_content(config_fmt, project_name, include_llm)
    _write(result, project_dir / cfg_name, cfg_content)

    # ── docker ────────────────────────────────────────────────────────────────
    _write(result, project_dir / "Dockerfile",          _dockerfile(project_name))
    _write(result, project_dir / "docker-compose.yml",  _docker_compose(project_name))

    # ── dependency file ───────────────────────────────────────────────────────
    if deps == "requirements":
        from infrakit.scaffolder.generator import _requirements_txt
        _write(result, project_dir / "requirements.txt",
               _requirements_txt(project_name))
    else:
        _write(result, project_dir / "pyproject.toml",
               _backend_pyproject(project_name, version, description, author))

    # ── repo files ────────────────────────────────────────────────────────────
    _write(result, project_dir / "README.md",   _backend_readme(project_name, description))
    _write(result, project_dir / ".gitignore",  _backend_gitignore())

    return result