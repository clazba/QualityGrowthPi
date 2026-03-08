"""ML trade filtering for the stat-arb strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any, Callable

import numpy as np

from src.models import MLFilterMode, MLTradeFilterDecision, PairCandidate, StatArbSettings
from src.stat_arb.model_loader import (
    LoadedModelArtifact,
    ModelArtifactError,
    load_model_artifact_from_path,
    ordered_feature_vector,
)


@dataclass(frozen=True)
class TradeFilterStatus:
    """Operational state for the active stat-arb trade filter."""

    configured_mode: str
    active_mode: str
    fallback_mode: str
    fallback_active: bool
    configured_model_key: str
    local_model_path: str
    loaded_model_version: str
    feature_schema_version: str
    load_status: str
    last_error: str | None = None
    artifact_source: str = "embedded"
    global_feature_importance: dict[str, float] | None = None

    def model_dump(self) -> dict[str, Any]:
        payload = {
            "configured_mode": self.configured_mode,
            "active_mode": self.active_mode,
            "fallback_mode": self.fallback_mode,
            "fallback_active": self.fallback_active,
            "configured_model_key": self.configured_model_key,
            "local_model_path": self.local_model_path,
            "loaded_model_version": self.loaded_model_version,
            "feature_schema_version": self.feature_schema_version,
            "load_status": self.load_status,
            "artifact_source": self.artifact_source,
        }
        if self.last_error:
            payload["last_error"] = self.last_error
        if self.global_feature_importance:
            payload["global_feature_importance"] = dict(self.global_feature_importance)
        return payload


class BaseTradeFilter:
    """Common filter interface for scorecard and artifact-backed inference."""

    def __init__(self, settings: StatArbSettings, status: TradeFilterStatus) -> None:
        self.settings = settings
        self.status = status

    def status_snapshot(self) -> dict[str, Any]:
        return self.status.model_dump()

    def score(self, candidate: PairCandidate) -> MLTradeFilterDecision:
        raise NotImplementedError


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _decision_metadata(status: TradeFilterStatus) -> dict[str, Any]:
    return status.model_dump()


def _top_feature_values(features: dict[str, float], limit: int = 4) -> dict[str, float]:
    return dict(
        sorted(
            ((name, round(value, 6)) for name, value in features.items()),
            key=lambda item: (-abs(item[1]), item[0]),
        )[:limit]
    )


class EmbeddedScorecardFilter(BaseTradeFilter):
    """Current embedded scorecard ensemble, preserved as the required fallback."""

    def score(self, candidate: PairCandidate) -> MLTradeFilterDecision:
        features, _ = ordered_feature_vector(candidate, self.settings)
        member_probabilities: list[float] = []
        aggregated_importance: dict[str, float] = {}
        votes = 0

        for member in self.settings.ml_filter.members:
            raw_score = member.intercept
            for feature_name, weight in member.weights.items():
                value = features.get(feature_name, 0.0)
                raw_score += value * weight
                aggregated_importance[feature_name] = aggregated_importance.get(feature_name, 0.0) + abs(value * weight)
            probability = _logistic(raw_score)
            member_probabilities.append(probability)
            if probability >= self.settings.ml_filter.probability_threshold:
                votes += 1

        predicted_probability = mean(member_probabilities)
        dispersion = pstdev(member_probabilities) if len(member_probabilities) > 1 else 0.0
        vote_ratio = votes / len(member_probabilities)
        confidence_score = max(
            0.0,
            min(
                1.0,
                ((abs(predicted_probability - 0.5) * 2.0) * 0.7)
                + ((1.0 - min(dispersion, 1.0)) * 0.15)
                + (vote_ratio * 0.15),
            ),
        )
        execute = (
            predicted_probability >= self.settings.ml_filter.probability_threshold
            and confidence_score >= self.settings.ml_filter.min_confidence
            and candidate.spread_features.expected_edge_bps >= self.settings.spread.min_expected_edge_bps
        )

        top_features = dict(
            sorted(
                ((name, round(value / len(member_probabilities), 6)) for name, value in aggregated_importance.items()),
                key=lambda item: (-item[1], item[0]),
            )[:4]
        )
        rationale = (
            f"mode={self.status.active_mode} model={self.settings.ml_filter.model_version} "
            f"prob={predicted_probability:.3f} confidence={confidence_score:.3f} "
            f"edge_bps={candidate.spread_features.expected_edge_bps:.1f} votes={votes}/{len(member_probabilities)}"
        )
        if self.status.fallback_active and self.status.last_error:
            rationale += f" fallback={self.status.last_error}"
        return MLTradeFilterDecision(
            pair_id=candidate.pair_id,
            cluster_id=candidate.cluster_id,
            execute=execute,
            predicted_win_probability=round(predicted_probability, 6),
            confidence_score=round(confidence_score, 6),
            expected_edge_bps=candidate.spread_features.expected_edge_bps,
            vote_ratio=round(vote_ratio, 6),
            model_version=self.settings.ml_filter.model_version,
            rationale=rationale,
            feature_importance=top_features,
            metadata=_decision_metadata(self.status),
        )


class ArtifactBackedSklearnFilter(BaseTradeFilter):
    """Artifact-backed sklearn inference using a validated joblib payload."""

    def __init__(
        self,
        settings: StatArbSettings,
        status: TradeFilterStatus,
        artifact: LoadedModelArtifact,
        fallback_filter_factory: Callable[[str], EmbeddedScorecardFilter],
    ) -> None:
        super().__init__(settings, status)
        self.artifact = artifact
        self._fallback_filter_factory = fallback_filter_factory

    def score(self, candidate: PairCandidate) -> MLTradeFilterDecision:
        features, ordered_values = ordered_feature_vector(candidate, self.settings)
        try:
            probabilities = self.artifact.pipeline.predict_proba([ordered_values])
        except Exception as exc:
            return self._fallback_filter_factory(f"Artifact predict_proba failed: {exc}").score(candidate)

        probabilities = np.asarray(probabilities, dtype=float)
        if probabilities.ndim != 2 or probabilities.shape[0] != 1 or probabilities.shape[1] < 2:
            return self._fallback_filter_factory(
                "Artifact predict_proba must return shape (1, n_classes>=2)"
            ).score(candidate)

        predicted_probability = float(probabilities[0][-1])
        confidence_score = round(max(0.0, min(1.0, abs(predicted_probability - 0.5) * 2.0)), 6)
        execute = (
            predicted_probability >= self.settings.ml_filter.probability_threshold
            and confidence_score >= self.settings.ml_filter.min_confidence
            and candidate.spread_features.expected_edge_bps >= self.settings.spread.min_expected_edge_bps
        )

        feature_importance = (
            dict(self.artifact.global_feature_importance)
            if self.artifact.global_feature_importance
            else _top_feature_values(features)
        )
        rationale = (
            f"mode={self.status.active_mode} model={self.artifact.model_version} "
            f"prob={predicted_probability:.3f} confidence={confidence_score:.3f} "
            f"edge_bps={candidate.spread_features.expected_edge_bps:.1f}"
        )
        return MLTradeFilterDecision(
            pair_id=candidate.pair_id,
            cluster_id=candidate.cluster_id,
            execute=execute,
            predicted_win_probability=round(predicted_probability, 6),
            confidence_score=confidence_score,
            expected_edge_bps=candidate.spread_features.expected_edge_bps,
            vote_ratio=1.0 if execute else 0.0,
            model_version=self.artifact.model_version,
            rationale=rationale,
            feature_importance=feature_importance,
            metadata=_decision_metadata(self.status),
        )


def _embedded_status(settings: StatArbSettings, *, fallback_active: bool, load_status: str, last_error: str | None = None) -> TradeFilterStatus:
    cfg = settings.ml_filter
    return TradeFilterStatus(
        configured_mode=cfg.mode.value,
        active_mode=MLFilterMode.EMBEDDED_SCORECARD.value,
        fallback_mode=cfg.fallback_mode.value,
        fallback_active=fallback_active,
        configured_model_key=cfg.object_store_model_key,
        local_model_path=cfg.local_model_path,
        loaded_model_version=cfg.model_version,
        feature_schema_version=cfg.feature_schema_version,
        load_status=load_status,
        last_error=last_error,
        artifact_source="embedded",
    )


def _artifact_status(settings: StatArbSettings, artifact: LoadedModelArtifact, *, artifact_source: str) -> TradeFilterStatus:
    cfg = settings.ml_filter
    return TradeFilterStatus(
        configured_mode=cfg.mode.value,
        active_mode=MLFilterMode.OBJECT_STORE_MODEL.value,
        fallback_mode=cfg.fallback_mode.value,
        fallback_active=False,
        configured_model_key=cfg.object_store_model_key,
        local_model_path=cfg.local_model_path,
        loaded_model_version=artifact.model_version,
        feature_schema_version=artifact.schema_version,
        load_status="loaded",
        artifact_source=artifact_source,
        global_feature_importance=dict(artifact.global_feature_importance),
    )


def build_trade_filter(
    settings: StatArbSettings,
    *,
    artifact_loader: Callable[[], LoadedModelArtifact] | None = None,
) -> BaseTradeFilter:
    """Build the configured stat-arb trade filter with required fallback behavior."""

    cfg = settings.ml_filter
    if cfg.mode == MLFilterMode.EMBEDDED_SCORECARD:
        return EmbeddedScorecardFilter(
            settings,
            _embedded_status(settings, fallback_active=False, load_status="embedded_primary"),
        )

    def _default_loader() -> LoadedModelArtifact:
        if not cfg.local_model_path:
            raise ModelArtifactError("object_store_model mode has no local_model_path configured for shared runtime")
        return load_model_artifact_from_path(
            cfg.local_model_path,
            expected_schema_version=cfg.feature_schema_version,
            expected_model_version=cfg.model_version,
        )

    try:
        artifact = (artifact_loader or _default_loader)()
    except ModelArtifactError as exc:
        return EmbeddedScorecardFilter(
            settings,
            _embedded_status(settings, fallback_active=True, load_status="fallback_after_load_error", last_error=str(exc)),
        )

    def _fallback_filter_factory(last_error: str) -> EmbeddedScorecardFilter:
        return EmbeddedScorecardFilter(
            settings,
            _embedded_status(
                settings,
                fallback_active=True,
                load_status="fallback_after_inference_error",
                last_error=last_error,
            ),
        )

    return ArtifactBackedSklearnFilter(
        settings,
        _artifact_status(settings, artifact, artifact_source="local_path"),
        artifact,
        _fallback_filter_factory,
    )


def score_pair_candidate(
    candidate: PairCandidate,
    settings: StatArbSettings,
    *,
    artifact_loader: Callable[[], LoadedModelArtifact] | None = None,
) -> MLTradeFilterDecision:
    """Score one pair candidate using the configured stat-arb ML filter."""

    trade_filter = build_trade_filter(settings, artifact_loader=artifact_loader)
    return trade_filter.score(candidate)
