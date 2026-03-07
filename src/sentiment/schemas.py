"""JSON schema loading and strict advisory payload validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from src.models import LLMAdvisoryOutput
from src.settings import resolve_project_path


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load a JSON schema from disk."""

    resolved_path = resolve_project_path(schema_path)
    with resolved_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_payload(payload: dict[str, Any], schema: dict[str, Any]) -> LLMAdvisoryOutput:
    """Validate a raw payload and coerce it into the canonical advisory model."""

    validate(instance=payload, schema=schema)
    return LLMAdvisoryOutput(**payload)


def try_validate_payload(payload: dict[str, Any], schema: dict[str, Any]) -> tuple[LLMAdvisoryOutput | None, str | None]:
    """Fail-soft validation helper used by the advisory engine."""

    try:
        model = validate_payload(payload, schema)
        return model, None
    except (ValidationError, ValueError) as exc:
        return None, str(exc)
