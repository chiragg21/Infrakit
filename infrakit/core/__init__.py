"""
infrakit.core
~~~~~~~~~~~~~
Core infrastructure: config management and structured logging.

Quick imports::

    from infrakit.core import setup, get_logger
    from infrakit.core import load, validate
"""

from infrakit.core.logger.setup import setup, get_logger, reset
from infrakit.core.config import (
    load,
    load_env,
    cast_value,
    detect_format,
    validate,
    Schema,
    field,
    convert_file,
    convert_dict,
    export_file,
    export_dict,
    export_string,
)

__all__ = [
    # logger
    "setup",
    "get_logger",
    "reset",
    # config
    "load",
    "load_env",
    "cast_value",
    "detect_format",
    "validate",
    "Schema",
    "field",
    "convert_file",
    "convert_dict",
    "export_file",
    "export_dict",
    "export_string",
]
