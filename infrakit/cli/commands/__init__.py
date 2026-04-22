"""infrakit.cli.commands — subcommand groups."""

from infrakit.cli.commands.config import config_app
from infrakit.cli.commands.logger import logger_app
from infrakit.cli.commands.module import module_app
from infrakit.cli.commands.time import time_app
from infrakit.cli.commands.deps import deps_app
from infrakit.cli.commands.llm import app as llm_app
from infrakit.cli.commands.init import cmd_init

__all__ = [
    "config_app",
    "logger_app",
    "module_app",
    "time_app",
    "deps_app",
    "llm_app",
    "cmd_init",
]
