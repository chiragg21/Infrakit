"""
infrakit.cli.main
~~~~~~~~~~~~~~~~~
Root Typer app. Registered as both ``infrakit`` and ``ik`` in pyproject.toml.

    [project.scripts]
    infrakit = "infrakit.cli.main:main"
    ik       = "infrakit.cli.main:main"
"""

import typer

from infrakit.cli.commands.config import config_app
from infrakit.cli.commands.logger import logger_app
from infrakit.cli.commands.module import module_app
from infrakit.cli.commands.init   import cmd_init
from infrakit.cli.commands.time import time_app
from infrakit.cli.commands.deps import deps_app

app = typer.Typer(
    name="infrakit",
    help="infrakit — developer infrastructure toolkit.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

app.add_typer(config_app, name="config")
app.add_typer(logger_app, name="logger")
app.add_typer(module_app, name="module")
app.add_typer(time_app, name="time")
app.add_typer(deps_app, name="deps")
app.command("init")(cmd_init)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version, PackageNotFoundError
        try:
            v = version("infrakit")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"infrakit {v}")
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """infrakit — developer infrastructure toolkit."""


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()