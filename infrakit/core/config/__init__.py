"""
infrakit.core.config
~~~~~~~~~~~~~~~~~~~~~
Configuration loading, validation, conversion, and export.

Quick imports::

    from infrakit.core.config import load, load_env, validate, Schema, field
    from infrakit.core.config import convert_file, convert_dict
    from infrakit.core.config import export_file, export_dict, export_string
"""

from infrakit.core.config.loader import (
    load,
    load_env,
    cast_value,
    cast_dict,
    detect_format,
    ConfigLoadError,
    UnsupportedFormatError,
    MissingDependencyError,
)
from infrakit.core.config.validator import (
    validate,
    Schema,
    field,
    FieldSpec,
    FieldError,
    ValidationResult,
    ConfigValidationError,
)
from infrakit.core.config.converter import (
    convert_file,
    convert_dict,
    ConversionError,
    ConversionWarning,
)
from infrakit.core.config.exporter import (
    export_file,
    export_dict,
    export_string,
)

__all__ = [
    # loader
    "load",
    "load_env",
    "cast_value",
    "cast_dict",
    "detect_format",
    "ConfigLoadError",
    "UnsupportedFormatError",
    "MissingDependencyError",
    # validator
    "validate",
    "Schema",
    "field",
    "FieldSpec",
    "FieldError",
    "ValidationResult",
    "ConfigValidationError",
    # converter
    "convert_file",
    "convert_dict",
    "ConversionError",
    "ConversionWarning",
    # exporter
    "export_file",
    "export_dict",
    "export_string",
]
