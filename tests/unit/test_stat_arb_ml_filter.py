"""Unit tests for the stat-arb ML trade filter."""

from __future__ import annotations

from datetime import UTC, datetime

from src.models import MLFilterMode, PairCandidate, SpreadFeatures
from src.settings import load_settings
from src.stat_arb.ml_filter import build_trade_filter, score_pair_candidate
from src.stat_arb.model_loader import LoadedModelArtifact, ModelArtifactError, validate_model_artifact


def _candidate(z_score: float, expected_edge_bps: float, correlation_stability: float = 0.8) -> PairCandidate:
    return PairCandidate(
        pair_id="cluster_001:AAPL:MSFT",
        cluster_id="cluster_001",
        first_symbol="AAPL",
        second_symbol="MSFT",
        spread_features=SpreadFeatures(
            pair_id="cluster_001:AAPL:MSFT",
            cluster_id="cluster_001",
            first_symbol="AAPL",
            second_symbol="MSFT",
            hedge_ratio=1.0,
            correlation=0.9,
            correlation_stability=correlation_stability,
            current_spread=0.4,
            spread_mean=0.0,
            spread_std=0.2,
            z_score=z_score,
            mean_reversion_speed=0.18,
            half_life_days=6.0,
            transaction_cost_bps=5.0,
            expected_edge_bps=expected_edge_bps,
            last_updated=datetime.now(UTC),
        ),
    )


def test_ml_trade_filter_accepts_high_quality_pair() -> None:
    settings = load_settings()
    decision = score_pair_candidate(_candidate(z_score=2.1, expected_edge_bps=42.0), settings.stat_arb)

    assert decision.execute is True
    assert decision.predicted_win_probability >= settings.stat_arb.ml_filter.probability_threshold


def test_ml_trade_filter_rejects_weak_edge_pair() -> None:
    settings = load_settings()
    decision = score_pair_candidate(_candidate(z_score=1.8, expected_edge_bps=6.0, correlation_stability=0.3), settings.stat_arb)

    assert decision.execute is False
    assert decision.expected_edge_bps == 6.0


class _ArtifactPipeline:
    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.18, 0.82]]


class _BrokenArtifactPipeline:
    def predict_proba(self, rows):
        raise RuntimeError("predict broke")


def test_validate_model_artifact_rejects_feature_order_mismatch() -> None:
    try:
        validate_model_artifact(
            {
                "schema_version": "stat_arb_v1",
                "model_version": "ensemble_v2",
                "feature_names": ["correlation", "abs_z_score"],
                "pipeline": _ArtifactPipeline(),
            },
            expected_schema_version="stat_arb_v1",
            expected_model_version="ensemble_v2",
        )
    except ModelArtifactError as exc:
        assert "feature_names" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected feature schema mismatch to raise ModelArtifactError")


def test_ml_trade_filter_uses_artifact_when_object_store_mode_is_enabled() -> None:
    settings = load_settings()
    stat_arb = settings.stat_arb.model_copy(
        update={
            "ml_filter": settings.stat_arb.ml_filter.model_copy(
                update={
                    "mode": MLFilterMode.OBJECT_STORE_MODEL,
                    "model_version": "ensemble_v2",
                    "local_model_path": "/tmp/fake.joblib",
                }
            )
        }
    )
    artifact = LoadedModelArtifact(
        schema_version="stat_arb_v1",
        model_version="ensemble_v2",
        feature_names=(
            "abs_z_score",
            "correlation",
            "correlation_stability",
            "mean_reversion_speed",
            "half_life_score",
            "expected_edge_bps_norm",
            "transaction_cost_penalty",
        ),
        pipeline=_ArtifactPipeline(),
        global_feature_importance={"expected_edge_bps_norm": 0.42},
    )

    trade_filter = build_trade_filter(stat_arb, artifact_loader=lambda: artifact)
    decision = trade_filter.score(_candidate(z_score=2.1, expected_edge_bps=42.0))

    assert decision.execute is True
    assert decision.model_version == "ensemble_v2"
    assert decision.metadata["active_mode"] == "object_store_model"
    assert decision.metadata["fallback_active"] is False
    assert decision.feature_importance["expected_edge_bps_norm"] == 0.42


def test_ml_trade_filter_falls_back_to_embedded_scorecard_on_artifact_load_error() -> None:
    settings = load_settings()
    stat_arb = settings.stat_arb.model_copy(
        update={
            "ml_filter": settings.stat_arb.ml_filter.model_copy(
                update={
                    "mode": MLFilterMode.OBJECT_STORE_MODEL,
                    "model_version": "ensemble_v2",
                    "local_model_path": "/tmp/missing.joblib",
                }
            )
        }
    )

    trade_filter = build_trade_filter(
        stat_arb,
        artifact_loader=lambda: (_ for _ in ()).throw(ModelArtifactError("boom")),
    )
    decision = trade_filter.score(_candidate(z_score=2.1, expected_edge_bps=42.0))

    assert decision.metadata["configured_mode"] == "object_store_model"
    assert decision.metadata["active_mode"] == "embedded_scorecard"
    assert decision.metadata["fallback_active"] is True
    assert decision.metadata["load_status"] == "fallback_after_load_error"
    assert "boom" in decision.rationale


def test_ml_trade_filter_falls_back_to_embedded_scorecard_on_inference_error() -> None:
    settings = load_settings()
    stat_arb = settings.stat_arb.model_copy(
        update={
            "ml_filter": settings.stat_arb.ml_filter.model_copy(
                update={
                    "mode": MLFilterMode.OBJECT_STORE_MODEL,
                    "model_version": "ensemble_v2",
                    "local_model_path": "/tmp/fake.joblib",
                }
            )
        }
    )
    artifact = LoadedModelArtifact(
        schema_version="stat_arb_v1",
        model_version="ensemble_v2",
        feature_names=(
            "abs_z_score",
            "correlation",
            "correlation_stability",
            "mean_reversion_speed",
            "half_life_score",
            "expected_edge_bps_norm",
            "transaction_cost_penalty",
        ),
        pipeline=_BrokenArtifactPipeline(),
    )

    trade_filter = build_trade_filter(stat_arb, artifact_loader=lambda: artifact)
    decision = trade_filter.score(_candidate(z_score=2.1, expected_edge_bps=42.0))

    assert decision.metadata["active_mode"] == "embedded_scorecard"
    assert decision.metadata["fallback_active"] is True
    assert decision.metadata["load_status"] == "fallback_after_inference_error"
    assert "predict broke" in decision.rationale
