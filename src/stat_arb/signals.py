"""Pair generation and spread feature computation."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import combinations
from typing import Iterable

import numpy as np

from src.models import ClusterSnapshot, PairCandidate, SpreadFeatures, StatArbSettings


def _align_price_series(left: list[float], right: list[float], max_points: int) -> tuple[np.ndarray, np.ndarray]:
    common_length = min(len(left), len(right), max_points)
    if common_length < 5:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    return (
        np.asarray(left[-common_length:], dtype=float),
        np.asarray(right[-common_length:], dtype=float),
    )


def _hedge_ratio(left: np.ndarray, right: np.ndarray) -> float:
    log_left = np.log(left)
    log_right = np.log(right)
    variance = float(np.var(log_left))
    if variance <= 0:
        return 1.0
    covariance = float(np.cov(log_right, log_left)[0, 1])
    return covariance / variance


def _spread_series(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, float]:
    hedge_ratio = _hedge_ratio(left, right)
    spread = np.log(right) - hedge_ratio * np.log(left)
    return spread, hedge_ratio


def _half_life_days(spread: np.ndarray) -> tuple[float, float]:
    lagged = spread[:-1]
    delta = np.diff(spread)
    if lagged.size < 5 or np.allclose(lagged, lagged[0]):
        return float("inf"), 0.0
    slope, intercept = np.polyfit(lagged, delta, 1)
    if np.isnan(slope) or slope >= 0:
        return float("inf"), 0.0
    half_life = float(np.log(2) / -slope)
    return half_life, float(-slope)


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
    first_closes: list[float],
    second_closes: list[float],
    settings: StatArbSettings,
    as_of: datetime,
) -> SpreadFeatures | None:
    """Return spread features for a single pair."""

    left, right = _align_price_series(
        first_closes,
        second_closes,
        max_points=max(
            settings.universe.lookback_days,
            settings.spread.zscore_lookback_days + 1,
            settings.graph.correlation_lookback_days + 1,
        ),
    )
    if left.size < settings.universe.min_history_days or right.size < settings.universe.min_history_days:
        return None

    correlation = float(np.corrcoef(np.diff(np.log(left)), np.diff(np.log(right)))[0, 1])
    if np.isnan(correlation):
        return None

    spread, hedge_ratio = _spread_series(left, right)
    lookback = spread[-settings.spread.zscore_lookback_days :]
    spread_mean = float(np.mean(lookback))
    spread_std = float(np.std(lookback))
    if spread_std <= 0:
        return None
    z_score = float((lookback[-1] - spread_mean) / spread_std)
    half_life, mean_reversion_speed = _half_life_days(spread)
    correlation_stability = _correlation_stability(left, right)
    expected_edge_bps = max(
        0.0,
        (abs(z_score) - settings.spread.take_profit_z_score)
        * max(mean_reversion_speed, 0.05)
        * 1_000.0
        - (settings.spread.transaction_cost_bps * 2.0),
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
        transaction_cost_bps=settings.spread.transaction_cost_bps,
        expected_edge_bps=round(expected_edge_bps, 6),
        last_updated=as_of.astimezone(UTC),
    )


def build_pair_candidates(
    clusters: Iterable[ClusterSnapshot],
    price_history: dict[str, list[float]],
    settings: StatArbSettings,
    as_of: datetime,
) -> list[PairCandidate]:
    """Generate candidate pairs from the current cluster set."""

    candidates: list[PairCandidate] = []
    for snapshot in clusters:
        cluster_candidates: list[PairCandidate] = []
        for first_symbol, second_symbol in combinations(snapshot.symbols, 2):
            pair_id = f"{snapshot.cluster_id}:{first_symbol}:{second_symbol}"
            spread_features = compute_spread_features(
                pair_id=pair_id,
                cluster_id=snapshot.cluster_id,
                first_symbol=first_symbol,
                second_symbol=second_symbol,
                first_closes=price_history[first_symbol],
                second_closes=price_history[second_symbol],
                settings=settings,
                as_of=as_of,
            )
            if spread_features is None:
                continue
            if abs(spread_features.z_score) < settings.spread.entry_z_score:
                continue
            if spread_features.half_life_days > settings.spread.max_half_life_days:
                continue
            if spread_features.correlation_stability < settings.spread.min_correlation_stability:
                continue
            cluster_candidates.append(
                PairCandidate(
                    pair_id=pair_id,
                    cluster_id=snapshot.cluster_id,
                    first_symbol=first_symbol,
                    second_symbol=second_symbol,
                    spread_features=spread_features,
                    metadata={
                        "direction": "short_first_long_second"
                        if spread_features.z_score > 0
                        else "long_first_short_second",
                        "average_cluster_correlation": snapshot.average_correlation,
                    },
                )
            )
        cluster_candidates.sort(
            key=lambda candidate: (
                -candidate.spread_features.expected_edge_bps,
                -abs(candidate.spread_features.z_score),
                candidate.pair_id,
            )
        )
        candidates.extend(cluster_candidates[: settings.graph.max_pairs_per_cluster])
    candidates.sort(
        key=lambda candidate: (
            -candidate.spread_features.expected_edge_bps,
            candidate.cluster_id,
            candidate.pair_id,
        )
    )
    return candidates
