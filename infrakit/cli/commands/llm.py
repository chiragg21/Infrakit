"""
infrakit/cli/commands/llm.py
-----------------------------
Typer command group for infrakit.llm — key status and quota management.

Commands
--------
    ik llm status
    ik llm status --provider openai
    ik llm status --key sk-abc123
    ik llm status --json

    ik llm quota set --provider openai --key sk-abc123 --rpm 60
    ik llm quota set --provider gemini  --key AIza-abc1 --daily 1000000 --reset-hour 0

Connecting to your main CLI
----------------------------
If your main entry point is a Typer app::

    # infrakit/cli/main.py  (or wherever your root app lives)
    from infrakit.cli.commands.llm import app as llm_app
    app.add_typer(llm_app, name="llm")

If your main entry point is a Click group (existing infrakit pattern)::

    # infrakit/cli/main.py
    from infrakit.cli.commands.llm import click_group as llm_group
    cli.add_command(llm_group, name="llm")
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

# ── enums for typer choices ────────────────────────────────────────────────

class ProviderChoice(str, Enum):
    openai = "openai"
    gemini = "gemini"


# ── shared option types (reused across commands) ───────────────────────────

_StorageDirOption = Annotated[
    Path,
    typer.Option(
        "--storage-dir", "-d",
        help="Directory where key state is persisted.",
        show_default=True,
    ),
]

_KeysFileOption = Annotated[
    Optional[Path],
    typer.Option(
        "--keys-file", "-k",
        help=(
            "JSON file containing API keys "
            '(format: {"openai_keys": [...], "gemini_keys": [...]}). '
            "Only needed to register new keys; omit when inspecting persisted state."
        ),
    ),
]

_ProviderFilterOption = Annotated[
    Optional[ProviderChoice],
    typer.Option(
        "--provider", "-p",
        help="Filter to a specific provider.",
        case_sensitive=False,
    ),
]

_KeyFilterOption = Annotated[
    Optional[str],
    typer.Option(
        "--key", "-K",
        help="Filter to a specific key (first 8 chars of the API key).",
    ),
]

# ── apps ───────────────────────────────────────────────────────────────────

# root app for this module — add_typer(llm_app, name="llm") in main
app = typer.Typer(
    name="llm",
    help="Manage infrakit LLM keys, quotas, and usage.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

# sub-app for quota subcommands
quota_app = typer.Typer(
    name="quota",
    help="Manage quota limits for LLM API keys.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
app.add_typer(quota_app, name="quota")


# ── helpers ────────────────────────────────────────────────────────────────

def _load_client(storage_dir: Path, keys_file: Optional[Path]):
    """
    Build a minimal LLMClient from CLI args.

    Loads keys from *keys_file* if given; otherwise passes empty lists so
    the client can still read already-persisted state from *storage_dir*.
    """
    from infrakit.llm import LLMClient

    keys: dict = {"openai_keys": [], "gemini_keys": []}

    if keys_file is not None:
        if keys_file.exists():
            with open(keys_file) as f:
                try:
                    keys = json.load(f)
                except json.JSONDecodeError as exc:
                    typer.echo(
                        f"[error] Could not parse keys file '{keys_file}': {exc}",
                        err=True,
                    )
                    raise typer.Exit(1)
        else:
            typer.echo(f"[warn] Keys file not found: {keys_file}", err=True)

    try:
        return LLMClient(keys=keys, storage_dir=storage_dir)
    except Exception as exc:
        typer.echo(f"[error] Failed to initialise LLMClient: {exc}", err=True)
        raise typer.Exit(1)


def _provider_str(provider: Optional[ProviderChoice]) -> Optional[str]:
    """Unwrap enum to plain string (or None)."""
    return provider.value if provider is not None else None


# ── ik llm status ──────────────────────────────────────────────────────────

@app.command("status")
def status(
    storage_dir: _StorageDirOption = Path("./logs"),
    keys_file: _KeysFileOption = None,
    provider: _ProviderFilterOption = None,
    key: _KeyFilterOption = None,
    output_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output raw JSON instead of formatted text.",
            is_flag=True,
        ),
    ] = False,
):
    """
    Show quota and usage status for LLM API keys.

    **Examples**

        ik llm status

        ik llm status --provider openai

        ik llm status --key sk-abc123

        ik llm status --json
    """
    client = _load_client(storage_dir, keys_file)
    prov = _provider_str(provider)

    rows = client.status(provider=prov, key_id=key)

    if not rows:
        typer.echo(
            "No keys found. Have you initialised the client with your keys?\n"
            "Tip: pass --keys-file to register keys on first use."
        )
        raise typer.Exit(0)

    if output_json:
        typer.echo(json.dumps(rows, indent=2, default=str))
        return

    client.print_status(provider=prov, key_id=key)


# ── ik llm quota set ───────────────────────────────────────────────────────

@quota_app.command("set")
def quota_set(
    provider: Annotated[
        ProviderChoice,
        typer.Option(
            "--provider", "-p",
            help="Provider the key belongs to.",
            case_sensitive=False,
        ),
    ],
    key: Annotated[
        str,
        typer.Option(
            "--key", "-K",
            help="Key ID — first 8 chars of the API key.",
        ),
    ],
    storage_dir: _StorageDirOption = Path("./logs"),
    keys_file: _KeysFileOption = None,
    rpm: Annotated[
        Optional[int],
        typer.Option("--rpm", help="Requests-per-minute limit. Omit to leave unchanged."),
    ] = None,
    tpm: Annotated[
        Optional[int],
        typer.Option("--tpm", help="Tokens-per-minute limit. Omit to leave unchanged."),
    ] = None,
    daily: Annotated[
        Optional[int],
        typer.Option("--daily", help="Daily token limit. Omit to leave unchanged."),
    ] = None,
    reset_hour: Annotated[
        int,
        typer.Option(
            "--reset-hour",
            help="UTC hour (0–23) at which the daily quota resets.",
            min=0,
            max=23,
            show_default=True,
        ),
    ] = 0,
):
    """
    Set quota limits for a specific API key.

    Only the options you pass are updated; omitted options are left unchanged.

    **Examples**

        ik llm quota set --provider openai --key sk-abc123 --rpm 60 --tpm 90000

        ik llm quota set --provider gemini --key AIza-abc1 --daily 1000000 --reset-hour 0
    """
    from infrakit.llm import QuotaConfig

    client = _load_client(storage_dir, keys_file)

    quota = QuotaConfig(
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

    # confirmation output
    lines = [f"Quota updated for {provider.value} key '{key}...' :"]
    lines.append(f"  RPM limit   : {rpm    if rpm    is not None else '(unchanged)'}")
    lines.append(f"  TPM limit   : {tpm    if tpm    is not None else '(unchanged)'}")
    lines.append(f"  Daily limit : {daily  if daily  is not None else '(unchanged)'}")
    lines.append(f"  Reset hour  : {reset_hour:02d}:00 UTC")
    typer.echo("\n".join(lines))


# ── click shim — for projects still using a Click root group ──────────────

def _make_click_group():
    """
    Return a Click CommandGroup wrapping this Typer app.

    Usage in a Click-based main CLI::

        from infrakit.cli.commands.llm import click_group
        cli.add_command(click_group, name="llm")
    """
    return typer.main.get_command(app)


click_group = _make_click_group()