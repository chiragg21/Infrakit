"""
infrakit/cli/commands/llm.py
-----------------------------
Typer command group for infrakit.llm — key status and quota management.

Commands
--------
    ik llm status
    ik llm status --provider openai
    ik llm status --key sk-abc123

    ik llm quota set --provider openai --key sk-abc123 --rpm 60
    ik llm quota set --provider gemini  --key AIza-abc1 --model gemini-2.5-pro --daily 250000
    ik llm quota set --provider gemini  --key AIza-abc1 --daily 1500000   # default for all models

Connecting to your main CLI
----------------------------
Typer root::

    from infrakit.cli.commands.llm import app as llm_app
    root_app.add_typer(llm_app, name="llm")

Click root::

    from infrakit.cli.commands.llm import click_group as llm_group
    cli.add_command(llm_group, name="llm")
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated


# ── enums ──────────────────────────────────────────────────────────────────

class ProviderChoice(str, Enum):
    openai = "openai"
    gemini = "gemini"


# ── shared option types ────────────────────────────────────────────────────

_StorageDirOption = Annotated[
    Optional[Path],
    typer.Option(
        "--storage-dir", "-d",
        help=(
            "Directory where key state is persisted. "
            "Defaults to ~/.infrakit/llm/"
        ),
    ),
]

_QuotaFileOption = Annotated[
    Optional[Path],
    typer.Option(
        "--quota-file", "-q",
        help=(
            "Path to quotas.json. "
            "Defaults to ~/.infrakit/llm/quotas.json if that file exists."
        ),
    ),
]

_KeysFileOption = Annotated[
    Optional[Path],
    typer.Option(
        "--keys-file", "-k",
        help=(
            'JSON file containing API keys: {"openai_keys": [...], "gemini_keys": [...]}. '
            "Only needed to register new keys; omit when inspecting persisted state."
        ),
    ),
]

_ProviderFilterOption = Annotated[
    Optional[ProviderChoice],
    typer.Option("--provider", "-p", help="Filter to a specific provider."),
]

_KeyFilterOption = Annotated[
    Optional[str],
    typer.Option("--key", "-K", help="Filter to a specific key (first 8 chars)."),
]


# ── apps ───────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="llm",
    help="Manage infrakit LLM keys, quotas, and usage.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

quota_app = typer.Typer(
    name="quota",
    help="Manage quota limits for LLM API keys.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
app.add_typer(quota_app, name="quota")


# ── helpers ────────────────────────────────────────────────────────────────

def _load_client(
    storage_dir: Optional[Path],
    quota_file: Optional[Path],
    keys_file: Optional[Path],
):
    from infrakit.llm import LLMClient

    keys: dict = {"openai_keys": [], "gemini_keys": []}
    if keys_file is not None:
        if keys_file.exists():
            with open(keys_file) as f:
                try:
                    keys = json.load(f)
                except json.JSONDecodeError as exc:
                    typer.echo(f"[error] Cannot parse keys file: {exc}", err=True)
                    raise typer.Exit(1)
        else:
            typer.echo(f"[warn] Keys file not found: {keys_file}", err=True)

    try:
        return LLMClient(
            keys=keys,
            storage_dir=storage_dir,
            quota_file=quota_file,
        )
    except Exception as exc:
        typer.echo(f"[error] Failed to initialise LLMClient: {exc}", err=True)
        raise typer.Exit(1)


def _prov(provider: Optional[ProviderChoice]) -> Optional[str]:
    return provider.value if provider is not None else None


# ── ik llm status ──────────────────────────────────────────────────────────

@app.command("status")
def status(
    storage_dir: _StorageDirOption = None,
    quota_file:  _QuotaFileOption  = None,
    keys_file:   _KeysFileOption   = None,
    provider:    _ProviderFilterOption = None,
    key:         _KeyFilterOption      = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON.", is_flag=True),
    ] = False,
):
    """
    Show quota and usage status for LLM API keys.

    Deactivation is tracked per model — a key can have gemini-2.5-pro
    exhausted while gemini-2.0-flash is still active.

    **Examples**

        ik llm status

        ik llm status --provider gemini

        ik llm status --key AIza-abc1

        ik llm status --json
    """
    client = _load_client(storage_dir, quota_file, keys_file)
    rows   = client.status(provider=_prov(provider), key_id=key)

    if not rows:
        typer.echo(
            "No keys found. Pass --keys-file to register keys on first use."
        )
        raise typer.Exit(0)

    if output_json:
        typer.echo(json.dumps(rows, indent=2, default=str))
        return

    client.print_status(provider=_prov(provider), key_id=key)


# ── ik llm quota set ───────────────────────────────────────────────────────

@quota_app.command("set")
def quota_set(
    provider: Annotated[
        ProviderChoice,
        typer.Option("--provider", "-p", help="Provider the key belongs to."),
    ],
    key: Annotated[
        str,
        typer.Option("--key", "-K", help="Key ID (first 8 chars of the API key)."),
    ],
    storage_dir: _StorageDirOption = None,
    quota_file:  _QuotaFileOption  = None,
    keys_file:   _KeysFileOption   = None,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model", "-m",
            help=(
                "Scope quota to a specific model "
                "(e.g. gemini-2.5-pro, gpt-4o). "
                "Omit to set a default that applies to all models on this key."
            ),
        ),
    ] = None,
    rpm: Annotated[
        Optional[int],
        typer.Option("--rpm", help="Requests-per-minute limit (key-level)."),
    ] = None,
    tpm: Annotated[
        Optional[int],
        typer.Option("--tpm", help="Tokens-per-minute limit (model-level)."),
    ] = None,
    daily: Annotated[
        Optional[int],
        typer.Option("--daily", help="Daily token limit (model-level)."),
    ] = None,
    reset_hour: Annotated[
        int,
        typer.Option(
            "--reset-hour",
            help="UTC hour (0-23) when daily quota resets.",
            min=0, max=23, show_default=True,
        ),
    ] = 0,
):
    """
    Set quota limits for a specific API key, optionally scoped to one model.

    Omitting **--model** sets a default that applies to all models on the key
    that don't have their own entry.  Providing **--model** overrides only
    that model.

    **Examples**

        # default for all models on this key
        ik llm quota set --provider gemini --key AIza-abc1 --rpm 15 --daily 1500000

        # tighter limit for one expensive model
        ik llm quota set --provider gemini --key AIza-abc1 \\
            --model gemini-2.5-pro --daily 250000 --reset-hour 0

        # openai key-level RPM
        ik llm quota set --provider openai --key sk-abc123 --rpm 60 --tpm 90000
    """
    from infrakit.llm import QuotaConfig

    client = _load_client(storage_dir, quota_file, keys_file)

    quota = QuotaConfig(
        model=model,
        rpm_limit=rpm,
        tpm_limit=tpm,
        daily_token_limit=daily,
        reset_hour_utc=reset_hour,
    )

    try:
        client.set_quota(provider=provider.value, key_id=key, quota=quota)
    except KeyError:
        typer.echo(
            f"[error] Key '{key}' not found for provider '{provider.value}'.\n"
            "Tip: key IDs are the first 8 characters of the raw API key.",
            err=True,
        )
        raise typer.Exit(1)

    scope = f"model '{model}'" if model else "all models (default)"
    lines = [f"Quota updated for {provider.value} key '{key}...' ({scope}):"]
    lines.append(f"  RPM limit   : {rpm   if rpm   is not None else '(unchanged)'}")
    lines.append(f"  TPM limit   : {tpm   if tpm   is not None else '(unchanged)'}")
    lines.append(f"  Daily limit : {daily if daily is not None else '(unchanged)'}")
    lines.append(f"  Reset hour  : {reset_hour:02d}:00 UTC")
    typer.echo("\n".join(lines))


# ── click shim ─────────────────────────────────────────────────────────────

def _make_click_group():
    return typer.main.get_command(app)

click_group = _make_click_group()