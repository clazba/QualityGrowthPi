"""Cloud-safe stat-arb helpers for the LEAN workspace."""

from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np


UTC = timezone.utc
STAT_ARB_FEATURE_NAMES: Tuple[str, ...] = (
    "abs_z_score",
    "correlation",
    "correlation_stability",
    "mean_reversion_speed",
    "half_life_score",
    "expected_edge_bps_norm",
    "transaction_cost_penalty",
)


class ModelArtifactError(RuntimeError):
    """Raised when the configured model artifact cannot be used safely."""


@dataclass(frozen=True)
class LoadedModelArtifact:
    schema_version: str
    model_version: str
    feature_names: Tuple[str, ...]
    pipeline: Any
    global_feature_importance: Dict[str, float] = field(default_factory=dict)
    training_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeFilterStatus:
    configured_mode: str
    active_mode: str
    fallback_mode: str
    fallback_active: bool
    configured_model_key: str
    local_model_path: str
    loaded_model_version: str
    feature_schema_version: str
    load_status: str
    last_error: str = ""
    artifact_source: str = "embedded"
    global_feature_importance: Dict[str, float] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
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


@dataclass(frozen=True)
class ClusterSnapshot:
    cluster_id: str
    as_of: datetime
    symbols: List[str]
    average_correlation: float
    edge_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpreadFeatures:
    pair_id: str
    cluster_id: str
    first_symbol: str
    second_symbol: str
    hedge_ratio: float
    correlation: float
    correlation_stability: float
    current_spread: float
    spread_mean: float
    spread_std: float
    z_score: float
    mean_reversion_speed: float
    half_life_days: float
    transaction_cost_bps: float
    expected_edge_bps: float
    last_updated: datetime


@dataclass(frozen=True)
class PairCandidate:
    pair_id: str
    cluster_id: str
    first_symbol: str
    second_symbol: str
    spread_features: SpreadFeatures
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MLTradeFilterDecision:
    pair_id: str
    cluster_id: str
    execute: bool
    predicted_win_probability: float
    confidence_score: float
    expected_edge_bps: float
    vote_ratio: float
    model_version: str
    rationale: str
    feature_importance: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PairTradeIntent:
    pair_id: str
    cluster_id: str
    long_symbol: str
    short_symbol: str
    long_weight: float
    short_weight: float
    gross_exposure: float
    net_exposure: float
    kelly_fraction: float
    entry_z_score: float
    expected_edge_bps: float
    decision: MLTradeFilterDecision
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PairPositionState:
    pair_id: str
    cluster_id: str
    long_symbol: str
    short_symbol: str
    opened_at: datetime
    status: str
    entry_z_score: float
    latest_z_score: float
    hedge_ratio: float
    gross_exposure: float
    net_exposure: float
    kelly_fraction: float
    stop_loss_z_score: float
    take_profit_z_score: float
    max_holding_days: int
    notes: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class StatArbCycle:
    as_of: datetime
    clusters: List[ClusterSnapshot]
    candidates: List[PairCandidate]
    decisions: Dict[str, MLTradeFilterDecision]
    intents: List[PairTradeIntent]
    exits: List[Dict[str, Any]]
    ml_filter_status: Dict[str, Any]


def load_strategy_config(path: Path) -> Dict[str, Any]:
    namespace: Dict[str, Any] = {}
    exec(path.read_text(encoding="utf-8"), namespace)
    config = dict(namespace["CONFIG"])
    strategy = config["strategy"]
    strategy["ml_filter"].setdefault("mode", "embedded_scorecard")
    strategy["ml_filter"].setdefault("object_store_model_key", "")
    strategy["ml_filter"].setdefault("local_model_path", "")
    strategy["ml_filter"].setdefault("feature_schema_version", "stat_arb_v1")
    strategy["ml_filter"].setdefault("fallback_mode", "embedded_scorecard")
    if not strategy["ml_filter"]["members"]:
        strategy["ml_filter"]["members"] = [
            {
                "name": "mean_reversion_core",
                "intercept": -0.15,
                "weights": {
                    "abs_z_score": 0.55,
                    "mean_reversion_speed": 0.90,
                    "correlation_stability": 0.80,
                    "expected_edge_bps_norm": 0.65,
                    "transaction_cost_penalty": -0.60,
                },
            },
            {
                "name": "fee_sensitivity",
                "intercept": -0.10,
                "weights": {
                    "abs_z_score": 0.35,
                    "half_life_score": 0.75,
                    "expected_edge_bps_norm": 0.80,
                    "transaction_cost_penalty": -0.85,
                },
            },
            {
                "name": "cluster_stability",
                "intercept": -0.05,
                "weights": {
                    "correlation": 0.60,
                    "correlation_stability": 0.95,
                    "half_life_score": 0.45,
                    "transaction_cost_penalty": -0.30,
                },
            },
            {
                "name": "extreme_move_guard",
                "intercept": -0.20,
                "weights": {
                    "abs_z_score": 0.95,
                    "mean_reversion_speed": 0.55,
                    "half_life_score": 0.40,
                    "transaction_cost_penalty": -0.50,
                },
            },
            {
                "name": "balanced_vote",
                "intercept": -0.12,
                "weights": {
                    "abs_z_score": 0.50,
                    "correlation": 0.35,
                    "correlation_stability": 0.55,
                    "expected_edge_bps_norm": 0.55,
                    "half_life_score": 0.35,
                    "transaction_cost_penalty": -0.45,
                },
            },
        ]
    return config


def _returns_from_closes(closes: Sequence[float], lookback_days: int) -> np.ndarray:
    trimmed = np.asarray(closes[-(lookback_days + 1) :], dtype=float)
    if trimmed.size < 3:
        return np.asarray([], dtype=float)
    return np.diff(np.log(trimmed))


def build_clusters(as_of: datetime, price_history: Dict[str, List[float]], config: Dict[str, Any]) -> List[ClusterSnapshot]:
    graph = config["strategy"]["graph"]
    correlations: Dict[Tuple[str, str], float] = {}
    adjacency: Dict[str, Dict[str, float]] = defaultdict(dict)
    returns_by_symbol = {
        symbol: _returns_from_closes(closes, int(graph["correlation_lookback_days"]))
        for symbol, closes in price_history.items()
    }
    for left, right in combinations(sorted(price_history), 2):
        left_returns = returns_by_symbol[left]
        right_returns = returns_by_symbol[right]
        common_length = min(left_returns.size, right_returns.size)
        if common_length < 5:
            continue
        correlation = float(np.corrcoef(left_returns[-common_length:], right_returns[-common_length:])[0, 1])
        if np.isnan(correlation):
            continue
        correlations[(left, right)] = correlation
        if correlation >= float(graph["min_correlation"]):
            adjacency[left][right] = correlation
            adjacency[right][left] = correlation

    seen: set[str] = set()
    clusters: List[ClusterSnapshot] = []
    cluster_index = 1
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [start]
        symbols: List[str] = []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            symbols.append(node)
            stack.extend(sorted(adjacency.get(node, {}), reverse=True))
        symbols.sort()
        if len(symbols) < int(graph["min_cluster_size"]):
            continue
        max_cluster_size = int(graph["max_cluster_size"])
        for index in range(0, len(symbols), max_cluster_size):
            chunk = symbols[index : index + max_cluster_size]
            if len(chunk) < int(graph["min_cluster_size"]):
                continue
            edges = [
                correlations.get((left, right), correlations.get((right, left), 0.0))
                for left, right in combinations(chunk, 2)
                if correlations.get((left, right), correlations.get((right, left), 0.0)) >= float(graph["min_correlation"])
            ]
            if not edges:
                continue
            clusters.append(
                ClusterSnapshot(
                    cluster_id=f"cluster_{cluster_index:03d}",
                    as_of=as_of.astimezone(UTC),
                    symbols=list(chunk),
                    average_correlation=round(float(np.mean(np.asarray(edges, dtype=float))), 6),
                    edge_count=len(edges),
                )
            )
            cluster_index += 1
    return clusters


def _align(left: Sequence[float], right: Sequence[float], max_points: int) -> Tuple[np.ndarray, np.ndarray]:
    common_length = min(len(left), len(right), max_points)
    if common_length < 5:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    return np.asarray(left[-common_length:], dtype=float), np.asarray(right[-common_length:], dtype=float)


def _spread_series(left: np.ndarray, right: np.ndarray) -> Tuple[np.ndarray, float]:
    log_left = np.log(left)
    log_right = np.log(right)
    variance = float(np.var(log_left))
    hedge_ratio = 1.0 if variance <= 0 else float(np.cov(log_right, log_left)[0, 1]) / variance
    return log_right - hedge_ratio * log_left, hedge_ratio


def _half_life(spread: np.ndarray) -> Tuple[float, float]:
    lagged = spread[:-1]
    delta = np.diff(spread)
    if lagged.size < 5 or np.allclose(lagged, lagged[0]):
        return float("inf"), 0.0
    slope, _intercept = np.polyfit(lagged, delta, 1)
    if np.isnan(slope) or slope >= 0:
        return float("inf"), 0.0
    return float(np.log(2) / -slope), float(-slope)


def _correlation_stability(left: np.ndarray, right: np.ndarray) -> float:
    left_returns = np.diff(np.log(left))
    right_returns = np.diff(np.log(right))
    common_length = min(left_returns.size, right_returns.size)
    if common_length < 6:
        return 0.0
    midpoint = common_length // 2
    prior_corr = float(np.corrcoef(left_returns[:midpoint], right_returns[:midpoint])[0, 1])
    recent_corr = float(np.corrcoef(left_returns[midpoint:], right_returns[midpoint:])[0, 1])
    if np.isnan(prior_corr) or np.isnan(recent_corr):
        return 0.0
    return max(0.0, 1.0 - min(1.0, abs(prior_corr - recent_corr)))


def compute_spread_features(
    pair_id: str,
    cluster_id: str,
    first_symbol: str,
    second_symbol: str,
    first_closes: List[float],
    second_closes: List[float],
    config: Dict[str, Any],
    as_of: datetime,
) -> SpreadFeatures | None:
    spread_cfg = config["strategy"]["spread"]
    universe = config["strategy"]["universe"]
    graph = config["strategy"]["graph"]
    max_points = max(
        int(universe["lookback_days"]),
        int(spread_cfg["zscore_lookback_days"]) + 1,
        int(graph["correlation_lookback_days"]) + 1,
    )
    left, right = _align(first_closes, second_closes, max_points)
    if left.size < int(universe["min_history_days"]) or right.size < int(universe["min_history_days"]):
        return None
    correlation = float(np.corrcoef(np.diff(np.log(left)), np.diff(np.log(right)))[0, 1])
    if np.isnan(correlation):
        return None
    spread, hedge_ratio = _spread_series(left, right)
    lookback = spread[-int(spread_cfg["zscore_lookback_days"]) :]
    spread_mean = float(np.mean(lookback))
    spread_std = float(np.std(lookback))
    if spread_std <= 0:
        return None
    z_score = float((lookback[-1] - spread_mean) / spread_std)
    half_life, mean_reversion_speed = _half_life(spread)
    correlation_stability = _correlation_stability(left, right)
    expected_edge_bps = max(
        0.0,
        (abs(z_score) - float(spread_cfg["take_profit_z_score"]))
        * max(mean_reversion_speed, 0.05)
        * 1000.0
        - (float(spread_cfg["transaction_cost_bps"]) * 2.0),
    )
    return SpreadFeatures(
        pair_id=pair_id,
        cluster_id=cluster_id,
        first_symbol=first_symbol,
        second_symbol=second_symbol,
        hedge_ratio=round(hedge_ratio, 6),
        correlation=round(correlation, 6),
        correlation_stability=round(correlation_stability, 6),
        current_spread=round(float(lookback[-1]), 6),
        spread_mean=round(spread_mean, 6),
        spread_std=round(spread_std, 6),
        z_score=round(z_score, 6),
        mean_reversion_speed=round(mean_reversion_speed, 6),
        half_life_days=round(float(half_life), 6) if np.isfinite(half_life) else float("inf"),
        transaction_cost_bps=float(spread_cfg["transaction_cost_bps"]),
        expected_edge_bps=round(expected_edge_bps, 6),
        last_updated=as_of.astimezone(UTC),
    )


def build_pair_candidates(
    clusters: Iterable[ClusterSnapshot],
    price_history: Dict[str, List[float]],
    config: Dict[str, Any],
    as_of: datetime,
) -> List[PairCandidate]:
    spread_cfg = config["strategy"]["spread"]
    graph_cfg = config["strategy"]["graph"]
    candidates: List[PairCandidate] = []
    for cluster in clusters:
        cluster_candidates: List[PairCandidate] = []
        for first_symbol, second_symbol in combinations(cluster.symbols, 2):
            pair_id = f"{cluster.cluster_id}:{first_symbol}:{second_symbol}"
            spread = compute_spread_features(
                pair_id,
                cluster.cluster_id,
                first_symbol,
                second_symbol,
                price_history[first_symbol],
                price_history[second_symbol],
                config,
                as_of,
            )
            if spread is None:
                continue
            if abs(spread.z_score) < float(spread_cfg["entry_z_score"]):
                continue
            if spread.half_life_days > float(spread_cfg["max_half_life_days"]):
                continue
            if spread.correlation_stability < float(spread_cfg["min_correlation_stability"]):
                continue
            cluster_candidates.append(
                PairCandidate(
                    pair_id=pair_id,
                    cluster_id=cluster.cluster_id,
                    first_symbol=first_symbol,
                    second_symbol=second_symbol,
                    spread_features=spread,
                    metadata={
                        "direction": "short_first_long_second" if spread.z_score > 0 else "long_first_short_second"
                    },
                )
            )
        cluster_candidates.sort(
            key=lambda candidate: (-candidate.spread_features.expected_edge_bps, candidate.pair_id)
        )
        candidates.extend(cluster_candidates[: int(graph_cfg["max_pairs_per_cluster"])])
    candidates.sort(key=lambda candidate: (-candidate.spread_features.expected_edge_bps, candidate.pair_id))
    return candidates


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + np.exp(-value))


def _normalized_features(candidate: PairCandidate, config: Dict[str, Any]) -> Dict[str, float]:
    spread_cfg = config["strategy"]["spread"]
    return {
        "abs_z_score": min(abs(candidate.spread_features.z_score) / float(spread_cfg["stop_loss_z_score"]), 1.5),
        "correlation": candidate.spread_features.correlation,
        "correlation_stability": candidate.spread_features.correlation_stability,
        "mean_reversion_speed": min(candidate.spread_features.mean_reversion_speed / 0.25, 1.5),
        "half_life_score": max(
            0.0,
            1.0
            - min(candidate.spread_features.half_life_days / float(spread_cfg["max_half_life_days"]), 1.0),
        ),
        "expected_edge_bps_norm": min(
            candidate.spread_features.expected_edge_bps / max(float(spread_cfg["min_expected_edge_bps"]) * 4.0, 1.0),
            2.0,
        ),
        "transaction_cost_penalty": min(
            candidate.spread_features.transaction_cost_bps / max(candidate.spread_features.expected_edge_bps, 1.0),
            2.0,
        ),
    }


def _ordered_feature_vector(features: Dict[str, float]) -> List[float]:
    return [float(features[name]) for name in STAT_ARB_FEATURE_NAMES]


def _top_feature_values(features: Dict[str, float], limit: int = 4) -> Dict[str, float]:
    return dict(
        sorted(
            ((name, round(value, 6)) for name, value in features.items()),
            key=lambda item: (-abs(item[1]), item[0]),
        )[:limit]
    )


def _require_mapping_value(payload: Dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ModelArtifactError(f"Missing required artifact field: {key}")
    return payload[key]


def _normalize_feature_names(feature_names: Sequence[str]) -> Tuple[str, ...]:
    normalized = tuple(str(name).strip() for name in feature_names)
    if normalized != STAT_ARB_FEATURE_NAMES:
        raise ModelArtifactError(
            "Artifact feature_names do not match the pinned stat-arb feature order. "
            f"expected={STAT_ARB_FEATURE_NAMES} actual={normalized}"
        )
    return normalized


def validate_model_artifact(
    payload: Any,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
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
    global_feature_importance = payload.get("global_feature_importance", {})
    if global_feature_importance is None:
        global_feature_importance = {}
    if not isinstance(global_feature_importance, dict):
        raise ModelArtifactError("global_feature_importance must be a dict when provided")
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
        global_feature_importance={str(key): float(value) for key, value in global_feature_importance.items()},
        training_metadata=dict(training_metadata),
    )


def _load_joblib_module():
    try:
        import joblib  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on cloud env
        raise ModelArtifactError("joblib is not installed in the current runtime") from exc
    return joblib


def load_model_artifact_from_bytes(
    serialized: bytes,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    joblib = _load_joblib_module()
    try:
        payload = joblib.load(io.BytesIO(serialized))
    except Exception as exc:  # pragma: no cover - defensive branch
        raise ModelArtifactError(f"Unable to deserialize model artifact: {exc}") from exc
    return validate_model_artifact(payload, expected_schema_version, expected_model_version)


def load_model_artifact_from_path(
    artifact_path: str,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    path = Path(artifact_path).expanduser().resolve()
    if not path.exists():
        raise ModelArtifactError(f"Model artifact path does not exist: {path}")
    return load_model_artifact_from_bytes(path.read_bytes(), expected_schema_version, expected_model_version)


def load_model_artifact_from_object_store(
    object_store: Any,
    object_store_model_key: str,
    expected_schema_version: str,
    expected_model_version: str,
) -> LoadedModelArtifact:
    if object_store is None:
        raise ModelArtifactError("ObjectStore is unavailable")
    if not object_store_model_key:
        raise ModelArtifactError("object_store_model_key is not configured")
    contains_key = getattr(object_store, "ContainsKey", None)
    read_bytes = getattr(object_store, "ReadBytes", None)
    if contains_key is None or read_bytes is None:
        raise ModelArtifactError("ObjectStore does not expose ContainsKey/ReadBytes")
    if not contains_key(object_store_model_key):
        raise ModelArtifactError(f"Object Store key not found: {object_store_model_key}")
    serialized = read_bytes(object_store_model_key)
    if not serialized:
        raise ModelArtifactError(f"Object Store key is empty: {object_store_model_key}")
    return load_model_artifact_from_bytes(serialized, expected_schema_version, expected_model_version)


def _embedded_status(config: Dict[str, Any], fallback_active: bool, load_status: str, last_error: str = "") -> TradeFilterStatus:
    ml_cfg = config["strategy"]["ml_filter"]
    return TradeFilterStatus(
        configured_mode=str(ml_cfg.get("mode", "embedded_scorecard")),
        active_mode="embedded_scorecard",
        fallback_mode=str(ml_cfg.get("fallback_mode", "embedded_scorecard")),
        fallback_active=fallback_active,
        configured_model_key=str(ml_cfg.get("object_store_model_key", "")),
        local_model_path=str(ml_cfg.get("local_model_path", "")),
        loaded_model_version=str(ml_cfg.get("model_version", "")),
        feature_schema_version=str(ml_cfg.get("feature_schema_version", "stat_arb_v1")),
        load_status=load_status,
        last_error=last_error,
        artifact_source="embedded",
    )


def _artifact_status(config: Dict[str, Any], artifact: LoadedModelArtifact, artifact_source: str) -> TradeFilterStatus:
    ml_cfg = config["strategy"]["ml_filter"]
    return TradeFilterStatus(
        configured_mode=str(ml_cfg.get("mode", "embedded_scorecard")),
        active_mode="object_store_model",
        fallback_mode=str(ml_cfg.get("fallback_mode", "embedded_scorecard")),
        fallback_active=False,
        configured_model_key=str(ml_cfg.get("object_store_model_key", "")),
        local_model_path=str(ml_cfg.get("local_model_path", "")),
        loaded_model_version=artifact.model_version,
        feature_schema_version=artifact.schema_version,
        load_status="loaded",
        artifact_source=artifact_source,
        global_feature_importance=dict(artifact.global_feature_importance),
    )


def _score_with_embedded_scorecard(
    candidate: PairCandidate,
    config: Dict[str, Any],
    status: TradeFilterStatus,
) -> MLTradeFilterDecision:
    ml_cfg = config["strategy"]["ml_filter"]
    spread_cfg = config["strategy"]["spread"]
    features = _normalized_features(candidate, config)
    probabilities: List[float] = []
    importance: Dict[str, float] = {}
    votes = 0
    threshold = float(ml_cfg["probability_threshold"])
    for member in ml_cfg["members"]:
        raw_score = float(member["intercept"])
        for feature_name, weight in member["weights"].items():
            value = features.get(feature_name, 0.0)
            raw_score += value * float(weight)
            importance[feature_name] = importance.get(feature_name, 0.0) + abs(value * float(weight))
        probability = float(_logistic(raw_score))
        probabilities.append(probability)
        if probability >= threshold:
            votes += 1
    predicted_probability = mean(probabilities)
    dispersion = pstdev(probabilities) if len(probabilities) > 1 else 0.0
    vote_ratio = votes / len(probabilities)
    confidence = max(
        0.0,
        min(
            1.0,
            ((abs(predicted_probability - 0.5) * 2.0) * 0.7)
            + ((1.0 - min(dispersion, 1.0)) * 0.15)
            + (vote_ratio * 0.15),
        ),
    )
    execute = (
        predicted_probability >= threshold
        and confidence >= float(ml_cfg["min_confidence"])
        and candidate.spread_features.expected_edge_bps >= float(spread_cfg["min_expected_edge_bps"])
    )
    top_features = dict(
        sorted(
            ((name, round(value / len(probabilities), 6)) for name, value in importance.items()),
            key=lambda item: (-item[1], item[0]),
        )[:4]
    )
    return MLTradeFilterDecision(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        execute=execute,
        predicted_win_probability=round(predicted_probability, 6),
        confidence_score=round(confidence, 6),
        expected_edge_bps=candidate.spread_features.expected_edge_bps,
        vote_ratio=round(vote_ratio, 6),
        model_version=str(ml_cfg["model_version"]),
        rationale=(
            f"mode={status.active_mode} model={ml_cfg['model_version']} prob={predicted_probability:.3f} "
            f"confidence={confidence:.3f} edge_bps={candidate.spread_features.expected_edge_bps:.1f}"
            + (f" fallback={status.last_error}" if status.fallback_active and status.last_error else "")
        ),
        feature_importance=top_features,
        metadata=status.model_dump(),
    )


def _score_with_loaded_artifact(
    candidate: PairCandidate,
    config: Dict[str, Any],
    artifact: LoadedModelArtifact,
    status: TradeFilterStatus,
) -> MLTradeFilterDecision:
    ml_cfg = config["strategy"]["ml_filter"]
    spread_cfg = config["strategy"]["spread"]
    features = _normalized_features(candidate, config)
    try:
        probabilities = np.asarray(artifact.pipeline.predict_proba([_ordered_feature_vector(features)]), dtype=float)
    except Exception as exc:
        fallback_status = _embedded_status(config, True, "fallback_after_inference_error", f"Artifact predict_proba failed: {exc}")
        return _score_with_embedded_scorecard(candidate, config, fallback_status)
    if probabilities.ndim != 2 or probabilities.shape[0] != 1 or probabilities.shape[1] < 2:
        fallback_status = _embedded_status(
            config,
            True,
            "fallback_after_inference_error",
            "Artifact predict_proba must return shape (1, n_classes>=2)",
        )
        return _score_with_embedded_scorecard(candidate, config, fallback_status)
    predicted_probability = float(probabilities[0][-1])
    confidence = max(0.0, min(1.0, abs(predicted_probability - 0.5) * 2.0))
    execute = (
        predicted_probability >= float(ml_cfg["probability_threshold"])
        and confidence >= float(ml_cfg["min_confidence"])
        and candidate.spread_features.expected_edge_bps >= float(spread_cfg["min_expected_edge_bps"])
    )
    feature_importance = (
        dict(artifact.global_feature_importance)
        if artifact.global_feature_importance
        else _top_feature_values(features)
    )
    return MLTradeFilterDecision(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        execute=execute,
        predicted_win_probability=round(predicted_probability, 6),
        confidence_score=round(confidence, 6),
        expected_edge_bps=candidate.spread_features.expected_edge_bps,
        vote_ratio=1.0 if execute else 0.0,
        model_version=artifact.model_version,
        rationale=(
            f"mode={status.active_mode} model={artifact.model_version} prob={predicted_probability:.3f} "
            f"confidence={confidence:.3f} edge_bps={candidate.spread_features.expected_edge_bps:.1f}"
        ),
        feature_importance=feature_importance,
        metadata=status.model_dump(),
    )


def build_trade_filter(
    config: Dict[str, Any],
    object_store: Any = None,
    artifact_loader: Any = None,
) -> Tuple[Any, TradeFilterStatus]:
    ml_cfg = config["strategy"]["ml_filter"]
    configured_mode = str(ml_cfg.get("mode", "embedded_scorecard")).strip().lower()
    if configured_mode == "embedded_scorecard":
        status = _embedded_status(config, False, "embedded_primary")
        def scorer(candidate: PairCandidate) -> MLTradeFilterDecision:
            return _score_with_embedded_scorecard(candidate, config, status)
        setattr(scorer, "status_snapshot", status.model_dump)
        return scorer, status

    expected_schema_version = str(ml_cfg.get("feature_schema_version", "stat_arb_v1"))
    expected_model_version = str(ml_cfg.get("model_version", "softvote_v2026_03_08"))
    object_store_model_key = str(ml_cfg.get("object_store_model_key", ""))
    local_model_path = str(ml_cfg.get("local_model_path", ""))
    try:
        if artifact_loader is not None:
            artifact = artifact_loader()
            status = _artifact_status(config, artifact, "injected")
        elif object_store is not None and object_store_model_key:
            artifact = load_model_artifact_from_object_store(
                object_store,
                object_store_model_key,
                expected_schema_version,
                expected_model_version,
            )
            status = _artifact_status(config, artifact, "object_store")
        elif local_model_path:
            artifact = load_model_artifact_from_path(
                local_model_path,
                expected_schema_version,
                expected_model_version,
            )
            status = _artifact_status(config, artifact, "local_path")
        else:
            raise ModelArtifactError("object_store_model mode has no object_store_model_key or local_model_path")
    except ModelArtifactError as exc:
        status = _embedded_status(config, True, "fallback_after_load_error", str(exc))
        def fallback_scorer(candidate: PairCandidate) -> MLTradeFilterDecision:
            return _score_with_embedded_scorecard(candidate, config, status)
        setattr(fallback_scorer, "status_snapshot", status.model_dump)
        return fallback_scorer, status
    def artifact_scorer(candidate: PairCandidate) -> MLTradeFilterDecision:
        return _score_with_loaded_artifact(candidate, config, artifact, status)
    setattr(artifact_scorer, "status_snapshot", status.model_dump)
    return artifact_scorer, status


def score_pair_candidate(
    candidate: PairCandidate,
    config: Dict[str, Any],
    object_store: Any = None,
    artifact_loader: Any = None,
) -> MLTradeFilterDecision:
    scorer, _status = build_trade_filter(config, object_store=object_store, artifact_loader=artifact_loader)
    return scorer(candidate)


def decayed_exit_thresholds(days_open: float, config: Dict[str, Any]) -> Tuple[float, float]:
    policy = config["strategy"]["exit_policy"]
    decay_factor = 0.5 ** (max(days_open, 0.0) / float(policy["decay_half_life_days"]))
    stop_loss = float(policy["minimum_stop_loss_z_score"]) + (
        float(policy["initial_stop_loss_z_score"]) - float(policy["minimum_stop_loss_z_score"])
    ) * decay_factor
    take_profit = float(policy["minimum_take_profit_z_score"]) + (
        float(policy["initial_take_profit_z_score"]) - float(policy["minimum_take_profit_z_score"])
    ) * decay_factor
    return round(stop_loss, 6), round(take_profit, 6)


def evaluate_pair_exit(
    state: PairPositionState,
    candidate: PairCandidate | None,
    config: Dict[str, Any],
    as_of: datetime,
) -> Dict[str, Any]:
    elapsed_days = max(0.0, (as_of.astimezone(UTC) - state.opened_at.astimezone(UTC)).total_seconds() / 86_400.0)
    stop_loss, take_profit = decayed_exit_thresholds(elapsed_days, config)
    current_z = candidate.spread_features.z_score if candidate is not None else state.latest_z_score
    reason = "hold"
    should_exit = False
    if abs(current_z) <= take_profit:
        should_exit = True
        reason = "take_profit"
    elif abs(current_z) >= stop_loss:
        should_exit = True
        reason = "stop_loss"
    elif elapsed_days >= int(config["strategy"]["exit_policy"]["max_holding_days"]):
        should_exit = True
        reason = "time_exit"
    elif candidate is None:
        should_exit = True
        reason = "signal_unavailable"
    return {
        "pair_id": state.pair_id,
        "should_exit": should_exit,
        "reason": reason,
        "stop_loss_z_score": stop_loss,
        "take_profit_z_score": take_profit,
        "current_z_score": round(current_z, 6),
    }


def _kelly_fraction(decision: MLTradeFilterDecision, config: Dict[str, Any]) -> float:
    sizing = config["strategy"]["sizing"]
    if not decision.execute or decision.predicted_win_probability < float(sizing["probability_floor"]):
        return 0.0
    payoff_ratio = max(float(sizing["payoff_ratio_floor"]), decision.expected_edge_bps / 25.0)
    probability = decision.predicted_win_probability
    raw_fraction = probability - ((1.0 - probability) / payoff_ratio)
    scaled = max(0.0, raw_fraction) * decision.confidence_score
    return min(float(sizing["max_fraction"]), max(float(sizing["min_fraction"]), scaled))


def build_pair_trade_intents(
    candidates: List[PairCandidate],
    decisions: Dict[str, MLTradeFilterDecision],
    config: Dict[str, Any],
    portfolio_equity: float,
    open_positions: List[PairPositionState],
) -> List[PairTradeIntent]:
    sizing = config["strategy"]["sizing"]
    if len([state for state in open_positions if state.status == "open"]) >= int(sizing["max_open_pairs"]):
        return []
    cluster_counts: Dict[str, int] = {}
    open_symbols = {
        symbol
        for state in open_positions
        if state.status == "open"
        for symbol in (state.long_symbol, state.short_symbol)
    }
    total_gross = sum(abs(state.gross_exposure) for state in open_positions if state.status == "open")
    total_net = sum(state.net_exposure for state in open_positions if state.status == "open")
    intents: List[PairTradeIntent] = []
    for candidate in candidates:
        decision = decisions.get(candidate.pair_id)
        if decision is None or not decision.execute:
            continue
        if len(intents) + len(open_positions) >= int(sizing["max_open_pairs"]):
            break
        if cluster_counts.get(candidate.cluster_id, 0) >= int(sizing["max_pairs_per_cluster"]):
            continue
        overlap_multiplier = 1.0
        if candidate.first_symbol in open_symbols or candidate.second_symbol in open_symbols:
            overlap_multiplier -= float(sizing["overlap_penalty"])
        kelly_fraction = _kelly_fraction(decision, config) * max(overlap_multiplier, 0.0)
        if kelly_fraction <= 0:
            continue
        gross_exposure = min(
            portfolio_equity * kelly_fraction,
            portfolio_equity * float(sizing["max_gross_exposure_per_trade"]),
            max(0.0, (portfolio_equity * float(sizing["max_gross_exposure_total"])) - total_gross),
        )
        if gross_exposure <= 0:
            continue
        half_weight = gross_exposure / (2.0 * portfolio_equity)
        direction_positive = candidate.spread_features.z_score <= 0
        long_symbol = candidate.first_symbol if direction_positive else candidate.second_symbol
        short_symbol = candidate.second_symbol if direction_positive else candidate.first_symbol
        long_weight = round(half_weight, 6)
        short_weight = round(-half_weight, 6)
        net_exposure = round(long_weight + short_weight, 6)
        if abs(total_net + net_exposure) > float(sizing["max_net_exposure_total"]):
            continue
        intents.append(
            PairTradeIntent(
                pair_id=candidate.pair_id,
                cluster_id=candidate.cluster_id,
                long_symbol=long_symbol,
                short_symbol=short_symbol,
                long_weight=long_weight,
                short_weight=short_weight,
                gross_exposure=round(gross_exposure / portfolio_equity, 6),
                net_exposure=net_exposure,
                kelly_fraction=round(kelly_fraction, 6),
                entry_z_score=candidate.spread_features.z_score,
                expected_edge_bps=decision.expected_edge_bps,
                decision=decision,
            )
        )
        total_gross += abs(intents[-1].gross_exposure)
        total_net += net_exposure
        cluster_counts[candidate.cluster_id] = cluster_counts.get(candidate.cluster_id, 0) + 1
        open_symbols.update({candidate.first_symbol, candidate.second_symbol})
    return intents


def run_stat_arb_cycle(
    config: Dict[str, Any],
    price_history: Dict[str, List[float]],
    as_of: datetime,
    portfolio_equity: float,
    open_positions: List[PairPositionState],
    trade_filter: Any = None,
    object_store: Any = None,
) -> StatArbCycle:
    clusters = build_clusters(as_of, price_history, config)
    candidates = build_pair_candidates(clusters, price_history, config, as_of)
    if trade_filter is None:
        trade_filter, filter_status = build_trade_filter(config, object_store=object_store)
    else:
        filter_status = getattr(trade_filter, "status_snapshot", None)
        if callable(filter_status):
            filter_status = filter_status()
        if filter_status is None:
            filter_status = {}
    decisions = {candidate.pair_id: trade_filter(candidate) for candidate in candidates}
    decision_fallbacks = [decision.metadata for decision in decisions.values() if decision.metadata.get("fallback_active")]
    if decision_fallbacks:
        latest = decision_fallbacks[0]
        filter_status["active_mode"] = latest.get("active_mode", filter_status.get("active_mode"))
        filter_status["fallback_active"] = True
        filter_status["load_status"] = latest.get("load_status", filter_status.get("load_status"))
        if latest.get("last_error"):
            filter_status["last_error"] = latest["last_error"]
    intents = build_pair_trade_intents(candidates, decisions, config, portfolio_equity, open_positions)
    candidate_map = {candidate.pair_id: candidate for candidate in candidates}
    exits = [
        evaluate_pair_exit(state, candidate_map.get(state.pair_id), config, as_of)
        for state in open_positions
        if state.status == "open"
    ]
    return StatArbCycle(
        as_of=as_of.astimezone(UTC),
        clusters=clusters,
        candidates=candidates,
        decisions=decisions,
        intents=intents,
        exits=exits,
        ml_filter_status=dict(filter_status),
    )
