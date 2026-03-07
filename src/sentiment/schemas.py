"""JSON schema loading and strict advisory payload validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from src.models import LLMAdvisoryOutput
from src.settings import resolve_project_path


_CONFIDENCE_LABELS = {
    "very_low": 0.1,
    "low": 0.25,
    "medium": 0.5,
    "med": 0.5,
    "high": 0.8,
    "very_high": 0.95,
}

_REPAIR_HINT_KEYS = {
    "confidence",
    "coverage",
    "reasoning",
    "reason",
    "catalysts",
    "risks",
    "tags",
}

_REQUIRED_SCHEMA_KEYS = {
    "symbol",
    "sentiment_score",
    "sentiment_label",
    "confidence_score",
    "key_catalysts",
    "key_risks",
    "narrative_tags",
    "event_urgency",
    "suggested_action",
    "rationale_short",
    "source_coverage_score",
    "model_name",
    "prompt_version",
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized in _CONFIDENCE_LABELS:
            return _CONFIDENCE_LABELS[normalized]
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_text(value: Any, fallback: str = "Insufficient structured rationale provided.") -> str:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized[:400]
    return fallback


def _normalize_action(value: Any) -> str:
    if not isinstance(value, str):
        return "no_effect"
    normalized = value.strip().lower()
    if normalized in {"no_effect", "caution", "manual_review", "reduce_size"}:
        return normalized
    return "no_effect"


def _derive_sentiment(action: str, raw_label: Any, raw_score: Any) -> tuple[str, float]:
    label = str(raw_label).strip().lower() if isinstance(raw_label, str) else ""
    score = _coerce_float(raw_score)

    if label in {"bullish", "neutral", "bearish", "unknown"}:
        if score is None:
            if label == "bullish":
                score = 0.4
            elif label == "bearish":
                score = -0.4
            else:
                score = 0.0
        return label, _clamp(score, -1.0, 1.0)

    if score is not None:
        clamped = _clamp(score, -1.0, 1.0)
        if clamped > 0.15:
            return "bullish", clamped
        if clamped < -0.15:
            return "bearish", clamped
        return "neutral", clamped

    if action == "reduce_size":
        return "bearish", -0.35
    if action == "caution":
        return "neutral", -0.1
    if action == "manual_review":
        return "unknown", 0.0
    return "neutral", 0.0


def repair_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce common alias-style model outputs into the strict advisory schema."""

    action = _normalize_action(payload.get("suggested_action"))
    confidence_score = _coerce_float(payload.get("confidence_score"))
    if confidence_score is None:
        confidence_score = _coerce_float(payload.get("confidence"))
    confidence_score = _clamp(confidence_score or 0.25, 0.0, 1.0)

    source_coverage_score = _coerce_float(payload.get("source_coverage_score"))
    if source_coverage_score is None:
        source_coverage_score = _coerce_float(payload.get("coverage"))
    if source_coverage_score is None:
        source_coverage_score = min(confidence_score, 0.25)
    source_coverage_score = _clamp(source_coverage_score, 0.0, 1.0)

    sentiment_label, sentiment_score = _derive_sentiment(
        action=action,
        raw_label=payload.get("sentiment_label"),
        raw_score=payload.get("sentiment_score"),
    )

    event_urgency = payload.get("event_urgency")
    if not isinstance(event_urgency, str) or event_urgency.strip().lower() not in {"low", "medium", "high", "unknown"}:
        event_urgency = "unknown"
    else:
        event_urgency = event_urgency.strip().lower()

    normalized = {
        "symbol": str(payload.get("symbol", "")).strip(),
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "confidence_score": confidence_score,
        "key_catalysts": _coerce_str_list(payload.get("key_catalysts") or payload.get("catalysts")),
        "key_risks": _coerce_str_list(payload.get("key_risks") or payload.get("risks")),
        "narrative_tags": _coerce_str_list(payload.get("narrative_tags") or payload.get("tags")),
        "event_urgency": event_urgency,
        "suggested_action": action,
        "rationale_short": _normalize_text(payload.get("rationale_short") or payload.get("reasoning") or payload.get("reason")),
        "source_coverage_score": source_coverage_score,
        "model_name": str(payload.get("model_name", "")).strip(),
        "prompt_version": str(payload.get("prompt_version", "")).strip(),
    }
    return normalized


def should_attempt_repair(payload: dict[str, Any]) -> bool:
    """Only repair likely Gemini alias-style outputs, not arbitrary invalid payloads."""

    payload_keys = set(payload.keys())
    if payload_keys & _REPAIR_HINT_KEYS:
        return True
    if not _REQUIRED_SCHEMA_KEYS.issubset(payload_keys):
        return True
    return False


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
        if not should_attempt_repair(payload):
            return None, str(exc)
        repaired = repair_payload(payload)
        try:
            model = validate_payload(repaired, schema)
            return model, None
        except (ValidationError, ValueError):
            return None, str(exc)
