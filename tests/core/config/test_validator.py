"""
tests/core/test_validator.py
Run with: uv run pytest tests/core/test_validator.py -v
"""
from __future__ import annotations
from typing import Optional
import pytest
from pydantic import BaseModel, field_validator
from infrakit.core.config.validator import (
    ConfigValidationError, FieldError, Schema,
    ValidationResult, field, validate,
)


# ---------------------------------------------------------------------------
# Sample Pydantic models
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    host: str
    port: int
    debug: bool = False


class DBConfig(BaseModel):
    host: str
    port: int
    name: str
    ssl: bool = False


class StrictConfig(BaseModel):
    env: str

    @field_validator("env")
    @classmethod
    def env_must_be_valid(cls, v: str) -> str:
        if v not in {"dev", "prod", "test"}:
            raise ValueError(f"env must be dev/prod/test, got '{v}'")
        return v


# ---------------------------------------------------------------------------
# Pydantic validation — happy path
# ---------------------------------------------------------------------------

class TestValidatePydantic:
    def test_valid_data_returns_ok(self):
        result = validate({"host": "localhost", "port": 8080}, AppConfig)
        assert result.ok
        assert result.data.host == "localhost"
        assert result.data.port == 8080

    def test_default_values_applied(self):
        result = validate({"host": "localhost", "port": 8080}, AppConfig)
        assert result.data.debug is False

    def test_result_is_model_instance(self):
        result = validate({"host": "localhost", "port": 8080}, AppConfig)
        assert isinstance(result.data, AppConfig)

    def test_bool_conversion(self):
        result = validate({"host": "localhost", "port": 8080}, AppConfig)
        assert result.ok

    def test_result_bool_is_true_on_success(self):
        result = validate({"host": "x", "port": 1}, AppConfig)
        assert bool(result) is True


class TestValidatePydanticErrors:
    def test_missing_required_field(self):
        result = validate({"host": "localhost"}, AppConfig)
        assert not result.ok
        fields = [e.field for e in result.errors]
        assert "port" in fields

    def test_wrong_type(self):
        result = validate({"host": "localhost", "port": "notanint"}, AppConfig)
        assert not result.ok

    def test_custom_validator_error(self):
        result = validate({"env": "staging"}, StrictConfig)
        assert not result.ok
        assert any("env" in e.field for e in result.errors)

    def test_multiple_errors_reported(self):
        result = validate({}, AppConfig)
        assert not result.ok
        assert len(result.errors) >= 2   # host and port both missing

    def test_errors_are_field_error_instances(self):
        result = validate({}, AppConfig)
        for e in result.errors:
            assert isinstance(e, FieldError)

    def test_raise_on_error(self):
        result = validate({}, AppConfig)
        with pytest.raises(ConfigValidationError):
            result.raise_on_error()

    def test_summary_contains_error_count(self):
        result = validate({}, AppConfig)
        summary = result.summary()
        assert "error" in summary.lower()

    def test_summary_ok(self):
        result = validate({"host": "x", "port": 1}, AppConfig)
        assert result.summary() == "Validation passed."


# ---------------------------------------------------------------------------
# Schema — happy path
# ---------------------------------------------------------------------------

class TestSchema:
    def test_valid_data(self):
        schema = Schema({"host": field(str), "port": field(int)})
        result = schema.validate({"host": "localhost", "port": 8080})
        assert result.ok
        assert result.data["port"] == 8080

    def test_optional_field_with_default(self):
        schema = Schema({
            "host": field(str),
            "debug": field(bool, required=False, default=False),
        })
        result = schema.validate({"host": "localhost"})
        assert result.ok
        assert result.data["debug"] is False

    def test_choices_valid(self):
        schema = Schema({"env": field(str, choices=["dev", "prod"])})
        result = schema.validate({"env": "dev"})
        assert result.ok

    def test_allow_extra_ignores_unknown_keys(self):
        schema = Schema({"host": field(str)}, allow_extra=True)
        result = schema.validate({"host": "x", "unknown": "y"})
        assert result.ok


class TestSchemaErrors:
    def test_missing_required_field(self):
        schema = Schema({"host": field(str), "port": field(int)})
        result = schema.validate({"host": "localhost"})
        assert not result.ok
        assert any(e.field == "port" for e in result.errors)

    def test_wrong_type_reported(self):
        schema = Schema({"port": field(int)})
        result = schema.validate({"port": "notanint"})
        assert not result.ok

    def test_invalid_choice(self):
        schema = Schema({"env": field(str, choices=["dev", "prod"])})
        result = schema.validate({"env": "staging"})
        assert not result.ok
        assert any("choices" in e.message.lower() or "one of" in e.message.lower()
                   for e in result.errors)

    def test_unknown_key_rejected_by_default(self):
        schema = Schema({"host": field(str)})
        result = schema.validate({"host": "x", "extra": "y"})
        assert not result.ok
        assert any(e.field == "extra" for e in result.errors)


class TestSchemaCoercion:
    def test_string_to_int(self):
        schema = Schema({"port": field(int)})
        result = schema.validate({"port": "8080"})
        assert result.ok
        assert result.data["port"] == 8080

    def test_string_to_bool_true(self):
        schema = Schema({"debug": field(bool)})
        result = schema.validate({"debug": "true"})
        assert result.ok
        assert result.data["debug"] is True

    def test_string_to_bool_false(self):
        schema = Schema({"debug": field(bool)})
        result = schema.validate({"debug": "false"})
        assert result.ok
        assert result.data["debug"] is False

    def test_int_to_float(self):
        schema = Schema({"ratio": field(float)})
        result = schema.validate({"ratio": 3})
        assert result.ok
        assert result.data["ratio"] == pytest.approx(3.0)

    def test_bool_not_coerced_to_int(self):
        # bool is a subclass of int — we reject this silently
        schema = Schema({"count": field(int)})
        result = schema.validate({"count": True})
        assert not result.ok