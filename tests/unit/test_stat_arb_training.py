from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
from sklearn.datasets import make_classification

from src.stat_arb.model_loader import STAT_ARB_FEATURE_NAMES, validate_model_artifact
from src.stat_arb.training import build_artifact_payload, build_training_samples, fit_soft_voting_ensemble
from src.strategy_settings import load_stat_arb_settings


def _training_settings():
    settings = load_stat_arb_settings()
    return replace(
        settings,
        graph=replace(
            settings.graph,
            min_correlation=0.4,
            max_pairs_per_cluster=3,
        ),
        spread=replace(
            settings.spread,
            entry_z_score=0.6,
            max_half_life_days=80.0,
            min_correlation_stability=0.0,
            min_expected_edge_bps=0.0,
        ),
        exit_policy=replace(
            settings.exit_policy,
            max_holding_days=10,
        ),
    )


def test_build_training_samples_generates_supervised_rows() -> None:
    settings = _training_settings()
    t = np.arange(160, dtype=float)
    trend = 0.002 * t
    base = np.exp(trend + 0.02 * np.sin(t / 12.0))
    price_history = {
        "AAPL": list(100.0 * base),
        "MSFT": list(101.0 * np.exp(trend + 0.02 * np.sin(t / 12.0 + 0.25) + 0.08 * np.sin(t / 5.5))),
        "NVDA": list(99.0 * np.exp(trend + 0.018 * np.sin(t / 11.5 - 0.1) - 0.07 * np.sin(t / 6.0))),
    }
    calendar = [
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index)).date().isoformat()
        for index in range(len(t))
    ]

    samples = build_training_samples(price_history, settings, calendar=calendar, sample_step=5)

    assert samples
    first = samples[0]
    assert set(first.features) == set(STAT_ARB_FEATURE_NAMES)
    assert first.label in {0, 1}
    assert isinstance(first.realized_return_bps, float)


def test_fit_soft_voting_ensemble_builds_valid_artifact() -> None:
    X, y = make_classification(
        n_samples=180,
        n_features=len(STAT_ARB_FEATURE_NAMES),
        n_informative=5,
        n_redundant=0,
        n_repeated=0,
        random_state=42,
    )
    result = fit_soft_voting_ensemble(
        X,
        y,
        cv_splits=3,
        random_state=42,
        n_jobs=1,
        model_param_grids={
            "mlp": {
                "model__hidden_layer_sizes": [(16,)],
                "model__alpha": [1e-4],
                "model__learning_rate_init": [1e-3],
            },
            "adaboost": {
                "model__n_estimators": [25],
                "model__learning_rate": [0.1],
            },
            "hist_gradient_boosting": {
                "model__learning_rate": [0.05],
                "model__max_depth": [3],
                "model__max_iter": [100],
                "model__l2_regularization": [0.0],
            },
            "sgd": {
                "model__alpha": [1e-4],
                "model__penalty": ["elasticnet"],
                "model__l1_ratio": [0.15],
            },
            "logistic_regression": {
                "model__C": [1.0],
                "model__class_weight": ["balanced"],
            },
        },
    )

    payload = build_artifact_payload(
        ensemble=result,
        model_version="softvote_test_v1",
        feature_schema_version="stat_arb_v1",
        training_metadata={"source": "unit_test"},
    )
    artifact = validate_model_artifact(
        payload,
        expected_schema_version="stat_arb_v1",
        expected_model_version="softvote_test_v1",
    )

    assert artifact.model_version == "softvote_test_v1"
    assert artifact.feature_names == STAT_ARB_FEATURE_NAMES
    assert hasattr(artifact.pipeline, "predict_proba")
