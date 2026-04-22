"""
infrakit
~~~~~~~~
A comprehensive Python developer infrastructure toolkit.

Quick imports::

    # Logging
    from infrakit import setup, get_logger

    # Config
    from infrakit import load, validate

    # LLM
    from infrakit import LLMClient

    # Dependencies
    from infrakit import deps

    # Scaffolding
    from infrakit import scaffolder

    # Profiling
    from infrakit import time
"""

from infrakit.core.logger.setup import setup, get_logger, reset
from infrakit.core.config import (
    load,
    load_env,
    validate,
    Schema,
    field,
    convert_file,
    convert_dict,
    export_file,
    export_dict,
    export_string,
)
from infrakit import deps, scaffolder, time

try:
    from infrakit.llm import LLMClient, LLMResponse, Prompt, QuotaConfig
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

__version__ = "0.1.4"

__all__ = [
    "__version__",
    # logging
    "setup",
    "get_logger",
    "reset",
    # config
    "load",
    "load_env",
    "validate",
    "Schema",
    "field",
    "convert_file",
    "convert_dict",
    "export_file",
    "export_dict",
    "export_string",
    # subpackages
    "deps",
    "scaffolder",
    "time",
]

if _LLM_AVAILABLE:
    __all__ += ["LLMClient", "LLMResponse", "Prompt", "QuotaConfig"]
