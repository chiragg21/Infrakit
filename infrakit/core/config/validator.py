"""
infrakit.core.config.validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Validate a loaded config dict against a Pydantic model or a lightweight
field-spec schema, with clear, structured error reporting.

Usage:
    # --- Pydantic model ---
    from pydantic import BaseModel
    from infrakit.core.config.validator import validate, ValidationResult

    class AppConfig(BaseModel):
        host: str
        port: int
        debug: bool = False

    result = validate({"host": "localhost", "port": 8080}, AppConfig)
    if result.ok:
        cfg = result.data          # AppConfig instance, fully typed
    else:
        print(result.errors)       # list[FieldError]

    # --- Dict schema (no Pydantic model needed) ---
    from infrakit.core.config.validator import Schema, field

    schema = Schema({
        "host":  field(str, required=True),
        "port":  field(int, required=True),
        "debug": field(bool, required=False, default=False),
    })
    result = schema.validate({"host": "localhost", "port": 8080})
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field as dc_field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ConfigDict = dict[str, Any]
T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldError:
    """A single validation failure on one field."""
    field: str          # dot-separated path, e.g. "database.port"
    message: str        # human-readable reason
    value: Any = None   # the offending value (None if field was missing)

    def __str__(self) -> str:
        location = f"[{self.field}]" if self.field else "[root]"
        suffix = f" (got {self.value!r})" if self.value is not None else ""
        return f"{location} {self.message}{suffix}"


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult(Generic[T]):
    """Outcome of a validate() call.

    Attributes
    ----------
    ok:
        True if validation passed with no errors.
    data:
        The validated model instance (Pydantic) or cast dict (Schema).
        ``None`` when *ok* is False.
    errors:
        List of :class:`FieldError` instances. Empty when *ok* is True.
    """
    ok: bool
    data: T | ConfigDict | None
    errors: list[FieldError] = dc_field(default_factory=list)

    def raise_on_error(self) -> None:
        """Raise :exc:`ConfigValidationError` if validation failed."""
        if not self.ok:
            raise ConfigValidationError(self.errors)

    def __bool__(self) -> bool:
        return self.ok

    def summary(self) -> str:
        """Return a human-readable multi-line summary of all errors."""
        if self.ok:
            return "Validation passed."
        lines = [f"Validation failed with {len(self.errors)} error(s):"]
        for err in self.errors:
            lines.append(f"  {err}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigValidationError(Exception):
    """Raised by :meth:`ValidationResult.raise_on_error` when validation fails."""

    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = errors
        super().__init__(self._format(errors))

    @staticmethod
    def _format(errors: list[FieldError]) -> str:
        lines = [f"Config validation failed ({len(errors)} error(s)):"]
        for err in errors:
            lines.append(f"  {err}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pydantic-based validation
# ---------------------------------------------------------------------------

def validate(data: ConfigDict, model: type[T]) -> ValidationResult[T]:
    """Validate *data* against a Pydantic *model*.

    Parameters
    ----------
    data:
        A plain config dict, as returned by :func:`~infrakit.core.config.loader.load`.
    model:
        A :class:`pydantic.BaseModel` subclass describing the expected shape.

    Returns
    -------
    ValidationResult[T]
        ``result.ok`` is True and ``result.data`` is the model instance on
        success. On failure, ``result.errors`` contains one :class:`FieldError`
        per invalid field.

    Examples
    --------
    >>> class DB(BaseModel):
    ...     host: str
    ...     port: int
    >>> result = validate({"host": "localhost", "port": 5432}, DB)
    >>> result.ok
    True
    >>> result.data.port
    5432
    """
    try:
        instance = model.model_validate(data)
        return ValidationResult(ok=True, data=instance, errors=[])
    except ValidationError as exc:
        errors = _parse_pydantic_errors(exc)
        return ValidationResult(ok=False, data=None, errors=errors)
    except Exception as exc:
        # Catch-all for unexpected failures (e.g. a broken model __init__)
        err = FieldError(field="", message=f"Unexpected error: {exc}")
        return ValidationResult(ok=False, data=None, errors=[err])


def _parse_pydantic_errors(exc: ValidationError) -> list[FieldError]:
    """Convert a Pydantic ValidationError into a list of FieldError."""
    errors: list[FieldError] = []
    for raw in exc.errors():
        # loc is a tuple like ("database", "port") or ("host",)
        loc = raw.get("loc", ())
        field_path = ".".join(str(part) for part in loc) if loc else ""
        message = raw.get("msg", "Invalid value")
        value = raw.get("input", None)
        errors.append(FieldError(field=field_path, message=message, value=value))
    return errors


# ---------------------------------------------------------------------------
# Lightweight dict schema
# ---------------------------------------------------------------------------

@dataclass
class FieldSpec:
    """Specification for a single config field in a :class:`Schema`.

    Attributes
    ----------
    type_:
        Expected Python type. ``None`` means any type is accepted.
    required:
        If True and the key is missing from the config dict, validation fails.
    default:
        Value used when the field is absent and *required* is False.
    choices:
        If provided, the value must be one of these options.
    description:
        Optional human-readable description (used in error messages and export).
    """
    type_: type | None = None
    required: bool = True
    default: Any = None
    choices: list[Any] | None = None
    description: str = ""


def field(
    type_: type | None = None,
    *,
    required: bool = True,
    default: Any = None,
    choices: list[Any] | None = None,
    description: str = "",
) -> FieldSpec:
    """Convenience constructor for :class:`FieldSpec`.

    Examples
    --------
    >>> schema = Schema({
    ...     "host":  field(str, required=True),
    ...     "port":  field(int, required=True),
    ...     "debug": field(bool, required=False, default=False),
    ...     "env":   field(str, choices=["dev", "prod", "test"]),
    ... })
    """
    return FieldSpec(
        type_=type_,
        required=required,
        default=default,
        choices=choices,
        description=description,
    )


class Schema:
    """A lightweight schema for validating config dicts without Pydantic.

    Useful when you want quick validation without defining a full model class,
    or when the config shape is determined at runtime.

    Parameters
    ----------
    fields:
        Mapping of field name -> :class:`FieldSpec` (use :func:`field` helper).
    allow_extra:
        If False (default), unknown keys in the config dict are reported as
        errors. If True, extra keys are silently ignored.

    Examples
    --------
    >>> schema = Schema({"port": field(int), "host": field(str)})
    >>> result = schema.validate({"port": 8080, "host": "localhost"})
    >>> result.ok
    True
    """

    def __init__(
        self,
        fields: dict[str, FieldSpec],
        *,
        allow_extra: bool = False,
    ) -> None:
        self._fields = fields
        self._allow_extra = allow_extra

    def validate(self, data: ConfigDict) -> ValidationResult:
        """Validate *data* against this schema.

        Returns
        -------
        ValidationResult
            ``result.data`` on success is a new dict with defaults filled in
            and values coerced to their declared types where possible.
        """
        errors: list[FieldError] = []
        result: ConfigDict = {}

        # Check declared fields
        for name, spec in self._fields.items():
            if name not in data:
                if spec.required:
                    errors.append(FieldError(
                        field=name,
                        message="Required field is missing.",
                    ))
                else:
                    result[name] = spec.default
                continue

            value = data[name]

            # Type check + coerce
            if spec.type_ is not None:
                value, type_error = _coerce(name, value, spec.type_)
                if type_error:
                    errors.append(type_error)
                    continue

            # Choices check
            if spec.choices is not None and value not in spec.choices:
                errors.append(FieldError(
                    field=name,
                    message=f"Must be one of {spec.choices}.",
                    value=value,
                ))
                continue

            result[name] = value

        # Check for unknown keys
        if not self._allow_extra:
            for key in data:
                if key not in self._fields:
                    errors.append(FieldError(
                        field=key,
                        message="Unknown field (not declared in schema).",
                        value=data[key],
                    ))

        if errors:
            return ValidationResult(ok=False, data=None, errors=errors)
        return ValidationResult(ok=True, data=result, errors=[])


# ---------------------------------------------------------------------------
# Type coercion helper
# ---------------------------------------------------------------------------

# Types we attempt to cast automatically (safe, lossless conversions only)
_SAFE_COERCIONS: dict[type, tuple[type, ...]] = {
    int:   (str, float),   # "8080" -> 8080, 8080.0 -> 8080
    float: (str, int),     # "3.14" -> 3.14, 3 -> 3.0
    bool:  (str,),         # "true" -> True  (via cast_value)
    str:   (int, float, bool),  # 42 -> "42"
}

_BOOL_TRUE  = {"true", "yes", "on",  "1"}
_BOOL_FALSE = {"false", "no",  "off", "0"}


def _coerce(
    name: str,
    value: Any,
    expected: type,
) -> tuple[Any, FieldError | None]:
    """Attempt to coerce *value* to *expected* type.

    Returns (coerced_value, None) on success,
            (value, FieldError) on failure.
    """
    if isinstance(value, expected):
        # bool is a subclass of int — guard against that
        if expected is int and isinstance(value, bool):
            return value, FieldError(
                field=name,
                message=f"Expected int, got bool.",
                value=value,
            )
        return value, None

    allowed_from = _SAFE_COERCIONS.get(expected, ())
    if not isinstance(value, allowed_from):
        return value, FieldError(
            field=name,
            message=f"Expected {expected.__name__}, got {type(value).__name__}.",
            value=value,
        )

    try:
        if expected is bool:
            if isinstance(value, str):
                lower = value.strip().lower()
                if lower in _BOOL_TRUE:
                    return True, None
                if lower in _BOOL_FALSE:
                    return False, None
                raise ValueError(f"Cannot interpret {value!r} as bool")
        coerced = expected(value)
        return coerced, None
    except (ValueError, TypeError) as exc:
        return value, FieldError(
            field=name,
            message=f"Cannot coerce to {expected.__name__}: {exc}",
            value=value,
        )