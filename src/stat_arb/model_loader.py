"""Artifact contract and feature-schema helpers for stat-arb model inference."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.models import PairCandidate, StatArbSettings


STAT_ARB_FEATURE_NAMES: tuple[str, ...] = (
    "abs_z_score",
    "correlation",
    "correlation_stability",
    "mean_reversion_speed",
    "half_life_score",
    "expected_edge_bps_norm",
    "transaction_cost_penalty",
)


class ModelArtifactError(RuntimeError):
    """Raised when a serialized stat-arb model artifact is unusable."""


@dataclass(frozen=True)
class LoadedModelArtifact:
    """Validated stat-arb model artifact."""

    schema_version: str
    model_version: str
    feature_names: tuple[str, ...]
    pipeline: Any
    global_feature_importance: dict[str, float] = field(default_factory=dict)
    training_metadata: dict[str, Any] = field(default_factory=dict)


def _require_mapping_value(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ModelArtifactError(f"Missing required artifact field: {key}")
    return payload[key]


def _normalize_feature_names(feature_names: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(name).strip() for name in feature_names)
    if normalized != STAT_ARB_FEATURE_NAMES:
        raise ModelArtifactError(
            "Artifact feature_names do not match the pinned stat-arb feature order. "
            f"expected={STAT_ARB_FEATURE_NAMES} actual={normalized}"
        )
    return normalized


def _normalize_feature_importance(payload: Any) -> dict[str, float]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ModelArtifactError("global_feature_importance must be a dict[str, float] when provided")
    normalized: dict[str, float] = {}
    for key, value in payload.items():
        normalized[str(key)] = float(value)
    return normalized


def validate_model_artifact(
    payload: Any,
    *,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    """Validate and normalize the serialized artifact contract."""

    if not isinstance(payload, dict):
        raise ModelArtifactError("Serialized model artifact must be a dict payload")

    schema_version = str(_require_mapping_value(payload, "schema_version")).strip()
    if schema_version != expected_schema_version:
        raise ModelArtifactError(
            "Artifact schema_version does not match config. "
            f"expected={expected_schema_version} actual={schema_version}"
        )

    model_version = str(_require_mapping_value(payload, "model_version")).strip()
    if model_version != expected_model_version:
        raise ModelArtifactError(
            "Artifact model_version does not match config. "
            f"expected={expected_model_version} actual={model_version}"
        )

    feature_names = _normalize_feature_names(_require_mapping_value(payload, "feature_names"))
    pipeline = _require_mapping_value(payload, "pipeline")
    if not hasattr(pipeline, "predict_proba"):
        raise ModelArtifactError("Artifact pipeline must expose predict_proba()")

    training_metadata = payload.get("training_metadata", {})
    if training_metadata is None:
        training_metadata = {}
    if not isinstance(training_metadata, dict):
        raise ModelArtifactError("training_metadata must be a dict when provided")

    return LoadedModelArtifact(
        schema_version=schema_version,
        model_version=model_version,
        feature_names=feature_names,
        pipeline=pipeline,
        global_feature_importance=_normalize_feature_importance(payload.get("global_feature_importance")),
        training_metadata=dict(training_metadata),
    )


def _load_joblib_module():
    try:
        import joblib  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise ModelArtifactError(
            "joblib is not installed. Install project dependencies before enabling object_store_model mode."
        ) from exc
    return joblib


def load_model_artifact_from_bytes(
    serialized: bytes,
    *,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    """Deserialize and validate a stat-arb model artifact from bytes."""

    joblib = _load_joblib_module()
    try:
        payload = joblib.load(io.BytesIO(serialized))
    except Exception as exc:  # pragma: no cover - defensive branch
        raise ModelArtifactError(f"Unable to deserialize model artifact: {exc}") from exc
    return validate_model_artifact(
        payload,
        expected_schema_version=expected_schema_version,
        expected_model_version=expected_model_version,
    )


def load_model_artifact_from_path(
    artifact_path: str | Path,
    *,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    """Load and validate a stat-arb model artifact from a local joblib file."""

    path = Path(artifact_path).expanduser().resolve()
    if not path.exists():
        raise ModelArtifactError(f"Model artifact path does not exist: {path}")
    serialized = path.read_bytes()
    return load_model_artifact_from_bytes(
        serialized,
        expected_schema_version=expected_schema_version,
        expected_model_version=expected_model_version,
    )


def normalized_feature_map(candidate: PairCandidate, settings: StatArbSettings) -> dict[str, float]:
    """Return the pinned stat-arb inference feature map for one candidate pair."""

    spread = candidate.spread_features
    max_half_life = max(settings.spread.max_half_life_days, 1.0)
    expected_edge_denominator = max(settings.spread.min_expected_edge_bps * 4.0, 1.0)
    transaction_denominator = max(spread.expected_edge_bps, 1.0)
    return {
        "abs_z_score": min(abs(spread.z_score) / settings.spread.stop_loss_z_score, 1.5),
        "correlation": spread.correlation,
        "correlation_stability": spread.correlation_stability,
        "mean_reversion_speed": min(spread.mean_reversion_speed / 0.25, 1.5),
        "half_life_score": max(0.0, 1.0 - min(spread.half_life_days / max_half_life, 1.0)),
        "expected_edge_bps_norm": min(spread.expected_edge_bps / expected_edge_denominator, 2.0),
        "transaction_cost_penalty": min(spread.transaction_cost_bps / transaction_denominator, 2.0),
    }


def ordered_feature_vector(candidate: PairCandidate, settings: StatArbSettings) -> tuple[dict[str, float], list[float]]:
    """Return the pinned feature map plus ordered vector expected by the model."""

    features = normalized_feature_map(candidate, settings)
    return features, [float(features[name]) for name in STAT_ARB_FEATURE_NAMES]
