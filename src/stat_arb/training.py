"""Offline training helpers for the graph stat-arb soft-voting ensemble."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.base import BaseEstimator, clone
from sklearn.ensemble import AdaBoostClassifier, HistGradientBoostingClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.models import PairCandidate, PairPositionState, StatArbSettings
from src.stat_arb.graph import build_clusters
from src.stat_arb.model_loader import STAT_ARB_FEATURE_NAMES, normalized_feature_map, validate_model_artifact
from src.stat_arb.risk import evaluate_pair_exit
from src.stat_arb.signals import build_pair_candidates, compute_spread_features


DEFAULT_MODEL_PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "mlp": {
        "model__hidden_layer_sizes": [(16,), (32,), (32, 16)],
        "model__alpha": [1e-4, 1e-3],
        "model__learning_rate_init": [1e-3, 5e-3],
    },
    "adaboost": {
        "model__n_estimators": [50, 100, 200],
        "model__learning_rate": [0.05, 0.1, 0.2],
    },
    "hist_gradient_boosting": {
        "model__learning_rate": [0.03, 0.05, 0.1],
        "model__max_depth": [3, 5, None],
        "model__max_iter": [100, 200],
        "model__l2_regularization": [0.0, 0.1],
    },
    "sgd": {
        "model__alpha": [1e-5, 1e-4, 1e-3],
        "model__penalty": ["l2", "elasticnet"],
        "model__l1_ratio": [0.15, 0.5],
    },
    "logistic_regression": {
        "model__C": [0.5, 1.0, 2.0, 4.0],
        "model__class_weight": [None, "balanced"],
    },
}


@dataclass(frozen=True)
class PairTradeOutcome:
    """Realized label and exit metadata for one candidate pair trade."""

    label: int
    realized_return_bps: float
    exit_reason: str
    exit_index: int
    holding_days: int


@dataclass(frozen=True)
class TrainingSample:
    """One supervised training example derived from a candidate spread trade."""

    pair_id: str
    cluster_id: str
    first_symbol: str
    second_symbol: str
    entry_index: int
    as_of: datetime
    features: dict[str, float]
    label: int
    realized_return_bps: float
    exit_reason: str
    holding_days: int

    def to_row(self) -> dict[str, Any]:
        payload = {
            "pair_id": self.pair_id,
            "cluster_id": self.cluster_id,
            "first_symbol": self.first_symbol,
            "second_symbol": self.second_symbol,
            "entry_index": self.entry_index,
            "as_of": self.as_of.isoformat(),
            "label": self.label,
            "realized_return_bps": round(self.realized_return_bps, 6),
            "exit_reason": self.exit_reason,
            "holding_days": self.holding_days,
        }
        payload.update({name: round(float(value), 6) for name, value in self.features.items()})
        return payload


@dataclass(frozen=True)
class FittedEnsembleResult:
    """Fitted soft-voting ensemble plus training metadata."""

    pipeline: VotingClassifier
    member_reports: dict[str, dict[str, Any]]
    ensemble_weights: dict[str, float]
    global_feature_importance: dict[str, float]


def load_price_history_json(path: str | Path) -> tuple[dict[str, list[float]], list[str] | None]:
    """Load aligned daily close history from JSON.

    Supported payloads:

    - ``{"AAPL": [...], "MSFT": [...]}``
    - ``{"calendar": [...], "price_history": {"AAPL": [...], ...}}``
    """

    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if "price_history" in payload:
        calendar = payload.get("calendar")
        price_history = payload["price_history"]
    else:
        calendar = None
        price_history = payload

    if not isinstance(price_history, dict) or not price_history:
        raise ValueError("price_history JSON must be a non-empty mapping of symbol -> list[close]")

    normalized: dict[str, list[float]] = {}
    min_length: int | None = None
    for raw_symbol, raw_series in price_history.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        if not isinstance(raw_series, list):
            raise ValueError(f"price_history[{symbol}] must be a list of closes")
        closes = [float(value) for value in raw_series]
        if len(closes) < 10:
            raise ValueError(f"price_history[{symbol}] must contain at least 10 closes")
        normalized[symbol] = closes
        min_length = len(closes) if min_length is None else min(min_length, len(closes))

    if len(normalized) < 2 or min_length is None:
        raise ValueError("price_history JSON must contain at least two populated symbols")

    aligned = {symbol: closes[-min_length:] for symbol, closes in normalized.items()}
    if calendar is None:
        return aligned, None
    if not isinstance(calendar, list):
        raise ValueError("calendar must be a list when provided")
    calendar_values = [str(value) for value in calendar[-min_length:]]
    return aligned, calendar_values


def _synthetic_calendar(length: int) -> list[str]:
    start = datetime(2000, 1, 1, tzinfo=UTC)
    return [(start + timedelta(days=index)).date().isoformat() for index in range(length)]


def _as_of_from_calendar(calendar: list[str] | None, index: int) -> datetime:
    value = (calendar or _synthetic_calendar(index + 1))[index]
    return datetime.fromisoformat(value).replace(tzinfo=UTC) if "T" not in value else datetime.fromisoformat(value).astimezone(UTC)


def _warmup_index(settings: StatArbSettings) -> int:
    return max(
        settings.universe.min_history_days,
        settings.graph.correlation_lookback_days + 1,
        settings.spread.zscore_lookback_days + 1,
    )


def _entry_position_state(candidate: PairCandidate, settings: StatArbSettings, opened_at: datetime) -> PairPositionState:
    direction_positive = candidate.spread_features.z_score <= 0
    long_symbol = candidate.first_symbol if direction_positive else candidate.second_symbol
    short_symbol = candidate.second_symbol if direction_positive else candidate.first_symbol
    return PairPositionState(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        long_symbol=long_symbol,
        short_symbol=short_symbol,
        opened_at=opened_at.astimezone(UTC),
        entry_z_score=candidate.spread_features.z_score,
        latest_z_score=candidate.spread_features.z_score,
        hedge_ratio=candidate.spread_features.hedge_ratio,
        gross_exposure=1.0,
        net_exposure=0.0,
        kelly_fraction=0.0,
        stop_loss_z_score=settings.exit_policy.initial_stop_loss_z_score,
        take_profit_z_score=settings.exit_policy.initial_take_profit_z_score,
        max_holding_days=settings.exit_policy.max_holding_days,
    )


def simulate_trade_outcome(
    candidate: PairCandidate,
    price_history: dict[str, list[float]],
    settings: StatArbSettings,
    *,
    entry_index: int,
    calendar: list[str] | None = None,
) -> PairTradeOutcome:
    """Replay one candidate pair forward under the current exit policy."""

    first_symbol = candidate.first_symbol
    second_symbol = candidate.second_symbol
    full_first = price_history[first_symbol]
    full_second = price_history[second_symbol]
    max_index = min(len(full_first), len(full_second)) - 1
    if entry_index >= max_index:
        raise ValueError("entry_index must leave at least one future bar for label generation")

    opened_at = _as_of_from_calendar(calendar, entry_index)
    state = _entry_position_state(candidate, settings, opened_at)
    long_entry = price_history[state.long_symbol][entry_index]
    short_entry = price_history[state.short_symbol][entry_index]

    exit_index = min(max_index, entry_index + settings.exit_policy.max_holding_days)
    exit_reason = "max_horizon"

    for future_index in range(entry_index + 1, min(max_index, entry_index + settings.exit_policy.max_holding_days) + 1):
        as_of = _as_of_from_calendar(calendar, future_index)
        spread_features = compute_spread_features(
            pair_id=candidate.pair_id,
            cluster_id=candidate.cluster_id,
            first_symbol=first_symbol,
            second_symbol=second_symbol,
            first_closes=full_first[: future_index + 1],
            second_closes=full_second[: future_index + 1],
            settings=settings,
            as_of=as_of,
        )
        live_candidate = None
        if spread_features is not None:
            live_candidate = PairCandidate(
                pair_id=candidate.pair_id,
                cluster_id=candidate.cluster_id,
                first_symbol=first_symbol,
                second_symbol=second_symbol,
                spread_features=spread_features,
                metadata=dict(candidate.metadata),
            )
        exit_signal = evaluate_pair_exit(state, live_candidate, settings, as_of)
        if bool(exit_signal["should_exit"]):
            exit_index = future_index
            exit_reason = str(exit_signal["reason"])
            break

    long_exit = price_history[state.long_symbol][exit_index]
    short_exit = price_history[state.short_symbol][exit_index]
    gross_log_return = 0.5 * (
        np.log(long_exit / long_entry) - np.log(short_exit / short_entry)
    )
    realized_return_bps = float((gross_log_return * 10_000.0) - (settings.spread.transaction_cost_bps * 2.0))
    return PairTradeOutcome(
        label=int(realized_return_bps > 0.0),
        realized_return_bps=round(realized_return_bps, 6),
        exit_reason=exit_reason,
        exit_index=exit_index,
        holding_days=exit_index - entry_index,
    )


def build_training_samples(
    price_history: dict[str, list[float]],
    settings: StatArbSettings,
    *,
    calendar: list[str] | None = None,
    sample_step: int = 1,
    max_samples: int = 0,
) -> list[TrainingSample]:
    """Generate supervised pair-trade examples from aligned close history."""

    if sample_step <= 0:
        raise ValueError("sample_step must be positive")
    symbols = sorted(price_history)
    if len(symbols) < 2:
        raise ValueError("at least two symbols are required")
    common_length = min(len(price_history[symbol]) for symbol in symbols)
    if common_length <= _warmup_index(settings):
        raise ValueError("price history is too short for stat-arb sample generation")

    training_calendar = calendar[-common_length:] if calendar else _synthetic_calendar(common_length)
    start_index = _warmup_index(settings) - 1
    final_entry_index = common_length - 2
    samples: list[TrainingSample] = []

    for entry_index in range(start_index, final_entry_index + 1, sample_step):
        as_of = _as_of_from_calendar(training_calendar, entry_index)
        truncated_history = {
            symbol: price_history[symbol][: entry_index + 1]
            for symbol in symbols
        }
        clusters = build_clusters(as_of, truncated_history, settings)
        candidates = build_pair_candidates(clusters, truncated_history, settings, as_of)
        for candidate in candidates:
            outcome = simulate_trade_outcome(
                candidate,
                price_history,
                settings,
                entry_index=entry_index,
                calendar=training_calendar,
            )
            features = normalized_feature_map(candidate, settings)
            samples.append(
                TrainingSample(
                    pair_id=candidate.pair_id,
                    cluster_id=candidate.cluster_id,
                    first_symbol=candidate.first_symbol,
                    second_symbol=candidate.second_symbol,
                    entry_index=entry_index,
                    as_of=as_of,
                    features=features,
                    label=outcome.label,
                    realized_return_bps=outcome.realized_return_bps,
                    exit_reason=outcome.exit_reason,
                    holding_days=outcome.holding_days,
                )
            )

    if max_samples > 0:
        return samples[-max_samples:]
    return samples


def samples_to_matrix(samples: list[TrainingSample]) -> tuple[np.ndarray, np.ndarray]:
    """Convert training samples into the pinned feature matrix and label vector."""

    if not samples:
        raise ValueError("at least one training sample is required")
    feature_matrix = np.asarray(
        [[float(sample.features[name]) for name in STAT_ARB_FEATURE_NAMES] for sample in samples],
        dtype=float,
    )
    labels = np.asarray([sample.label for sample in samples], dtype=int)
    return feature_matrix, labels


def _estimator_specs(random_state: int) -> dict[str, BaseEstimator]:
    return {
        "mlp": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPClassifier(
                        hidden_layer_sizes=(32,),
                        alpha=1e-4,
                        learning_rate_init=1e-3,
                        max_iter=800,
                        early_stopping=True,
                        n_iter_no_change=20,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "adaboost": Pipeline(
            steps=[
                ("model", AdaBoostClassifier(random_state=random_state)),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            steps=[
                ("model", HistGradientBoostingClassifier(random_state=random_state)),
            ]
        ),
        "sgd": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "model",
                    SGDClassifier(
                        loss="log_loss",
                        penalty="elasticnet",
                        alpha=1e-4,
                        l1_ratio=0.15,
                        class_weight="balanced",
                        max_iter=2_000,
                        tol=1e-4,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "logistic_regression": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        solver="lbfgs",
                        max_iter=2_000,
                        class_weight="balanced",
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def _resolve_cv_splits(sample_count: int, requested_splits: int) -> int:
    max_splits = max(2, min(requested_splits, (sample_count // 20) or 2))
    if sample_count < (max_splits + 2):
        raise ValueError("not enough samples for the requested number of time-series CV splits")
    return max_splits


def _normalized_model_weights(best_scores: dict[str, float]) -> dict[str, float]:
    raw_scores = np.asarray([best_scores[name] for name in best_scores], dtype=float)
    finite_scores = np.where(np.isfinite(raw_scores), raw_scores, np.nan)
    if np.isnan(finite_scores).all():
        return {name: 1.0 for name in best_scores}
    minimum = np.nanmin(finite_scores)
    shifted = np.asarray([(score - minimum) + 1e-6 for score in finite_scores], dtype=float)
    if float(np.sum(shifted)) <= 0:
        return {name: 1.0 for name in best_scores}
    normalized = shifted / float(np.sum(shifted))
    return {
        name: round(float(normalized[index]), 6)
        for index, name in enumerate(best_scores)
    }


def _extract_model_feature_importance(estimator: BaseEstimator) -> np.ndarray | None:
    model = estimator
    if isinstance(estimator, Pipeline):
        model = estimator.named_steps["model"]
    if hasattr(model, "coef_"):
        values = np.asarray(getattr(model, "coef_"), dtype=float)
        if values.ndim == 2:
            return np.mean(np.abs(values), axis=0)
        return np.abs(values)
    if hasattr(model, "feature_importances_"):
        return np.asarray(getattr(model, "feature_importances_"), dtype=float)
    return None


def _aggregate_feature_importance(
    fitted_estimators: dict[str, BaseEstimator],
    ensemble_weights: dict[str, float],
) -> dict[str, float]:
    aggregate = np.zeros(len(STAT_ARB_FEATURE_NAMES), dtype=float)
    contributed = False
    for name, estimator in fitted_estimators.items():
        values = _extract_model_feature_importance(estimator)
        if values is None or values.shape[0] != len(STAT_ARB_FEATURE_NAMES):
            continue
        total = float(np.sum(np.abs(values)))
        if total <= 0:
            continue
        aggregate += (np.abs(values) / total) * ensemble_weights.get(name, 1.0)
        contributed = True
    if not contributed or float(np.sum(aggregate)) <= 0:
        return {}
    aggregate /= float(np.sum(aggregate))
    return {
        feature_name: round(float(aggregate[index]), 6)
        for index, feature_name in enumerate(STAT_ARB_FEATURE_NAMES)
    }


def fit_soft_voting_ensemble(
    X: np.ndarray,
    y: np.ndarray,
    *,
    cv_splits: int = 5,
    scoring: str = "neg_log_loss",
    random_state: int = 42,
    n_jobs: int | None = None,
    selected_estimators: list[str] | None = None,
    model_param_grids: dict[str, dict[str, list[Any]]] | None = None,
) -> FittedEnsembleResult:
    """Train the five-model soft-voting ensemble with walk-forward CV."""

    if X.ndim != 2 or X.shape[1] != len(STAT_ARB_FEATURE_NAMES):
        raise ValueError("feature matrix must be 2D and match the pinned stat-arb feature order")
    unique_labels = sorted(set(int(value) for value in y.tolist()))
    if unique_labels != [0, 1]:
        raise ValueError("training labels must contain both classes 0 and 1")

    estimator_specs = _estimator_specs(random_state)
    estimator_names = selected_estimators or list(estimator_specs)
    param_grids = model_param_grids or DEFAULT_MODEL_PARAM_GRIDS
    splitter = TimeSeriesSplit(n_splits=_resolve_cv_splits(len(X), cv_splits))

    fitted_members: dict[str, BaseEstimator] = {}
    member_reports: dict[str, dict[str, Any]] = {}
    best_scores: dict[str, float] = {}

    for name in estimator_names:
        if name not in estimator_specs:
            raise ValueError(f"Unknown estimator '{name}'. Available: {', '.join(sorted(estimator_specs))}")
        search = GridSearchCV(
            estimator=estimator_specs[name],
            param_grid=param_grids[name],
            cv=splitter,
            scoring=scoring,
            n_jobs=n_jobs,
            refit=True,
            error_score=np.nan,
        )
        search.fit(X, y)
        best_score = float(search.best_score_)
        if not np.isfinite(best_score):
            continue
        fitted_members[name] = clone(search.best_estimator_)
        member_reports[name] = {
            "best_score": round(best_score, 6),
            "best_params": search.best_params_,
        }
        best_scores[name] = best_score

    if len(fitted_members) < 2:
        raise ValueError("At least two ensemble members must fit successfully to build the soft-voting model")

    ensemble_weights = _normalized_model_weights(best_scores)
    voting = VotingClassifier(
        estimators=[(name, estimator) for name, estimator in fitted_members.items()],
        voting="soft",
        weights=[ensemble_weights[name] for name in fitted_members],
        n_jobs=n_jobs,
    )
    voting.fit(X, y)
    fitted_named_estimators = {
        name: voting.named_estimators_[name]
        for name in fitted_members
    }
    global_feature_importance = _aggregate_feature_importance(fitted_named_estimators, ensemble_weights)

    for name, weight in ensemble_weights.items():
        member_reports[name]["ensemble_weight"] = round(weight, 6)

    return FittedEnsembleResult(
        pipeline=voting,
        member_reports=member_reports,
        ensemble_weights=ensemble_weights,
        global_feature_importance=global_feature_importance,
    )


def build_artifact_payload(
    *,
    ensemble: FittedEnsembleResult,
    model_version: str,
    feature_schema_version: str,
    training_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate the exact serialized artifact contract."""

    metadata = dict(training_metadata or {})
    metadata.setdefault("sklearn_version", sklearn.__version__)
    metadata.setdefault("joblib_version", joblib.__version__)
    metadata.setdefault("generated_at", datetime.now(UTC).isoformat())
    payload = {
        "schema_version": feature_schema_version,
        "model_version": model_version,
        "feature_names": list(STAT_ARB_FEATURE_NAMES),
        "pipeline": ensemble.pipeline,
        "global_feature_importance": dict(ensemble.global_feature_importance),
        "training_metadata": metadata,
    }
    validate_model_artifact(
        payload,
        expected_schema_version=feature_schema_version,
        expected_model_version=model_version,
    )
    return payload


def save_training_samples_jsonl(samples: list[TrainingSample], path: str | Path) -> None:
    """Persist the generated supervised samples for audit and debugging."""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_row(), sort_keys=True) + "\n")

