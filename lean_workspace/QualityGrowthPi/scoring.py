"""Cloud-safe scoring and timing helpers for the LEAN workspace project."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np


UTC = timezone.utc
Z_SCORE_CAP = 3.0
SECTOR_RELATIVE_METRICS = ("roe", "revenue_growth", "net_income_growth")


@dataclass(frozen=True)
class FundamentalSnapshot:
    """Minimal fundamental snapshot required by the LEAN cloud algorithm."""

    symbol: str
    as_of: datetime
    has_fundamental_data: bool
    market_cap: float
    exchange_id: str
    price: float
    volume: float
    sector_code: Optional[str] = None
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    net_income_growth: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None


@dataclass(frozen=True)
class TimingFeatures:
    """Daily-bar timing overlay state."""

    symbol: str
    relative_volume: float
    volatility_ratio: float
    short_sma: float
    long_sma: float
    trend_up: bool
    volatility_contraction: bool
    timing_score: float
    last_updated: datetime


@dataclass(frozen=True)
class RankedCandidate:
    """Ranked symbol with fundamental, timing, and combined scores."""

    symbol: str
    fundamental_score: float
    timing_score: float = 0.0
    combined_score: float = 0.0
    target_weight: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RebalanceIntent:
    """Deterministic rebalance output."""

    rebalance_key: str
    selected_symbols: List[str]
    target_weights: Dict[str, float]
    scored_candidates: List[RankedCandidate]
    metadata: Dict[str, Any]


def load_strategy_config(config_path: Path) -> Dict[str, Any]:
    """Load the cloud-safe strategy config from the project-local config file."""

    if config_path.suffix == ".py":
        namespace: Dict[str, Any] = {}
        exec(config_path.read_text(encoding="utf-8"), namespace)
        payload = namespace.get("CONFIG")
    else:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Missing CONFIG dictionary in {config_path}")
    strategy = payload.get("strategy")
    if not isinstance(strategy, dict):
        raise ValueError(f"Missing strategy block in {config_path}")
    runtime = payload.get("runtime", {})
    return {"strategy": strategy, "runtime": runtime}


def tolerate_missing_net_income_growth(value: Optional[float]) -> bool:
    """Mirror the adjusted strategy's permissive handling for missing or zero values."""

    return value is None or value == 0


def _normalize_by_symbol(values: Dict[str, float]) -> Dict[str, float]:
    """Normalize a cross-section with capped z-scores."""

    if not values:
        return {}
    mean = sum(values.values()) / len(values)
    variance = sum((value - mean) ** 2 for value in values.values()) / len(values)
    if variance <= 0:
        return {symbol: 0.0 for symbol in values}
    std_dev = math.sqrt(variance)
    return {
        symbol: max(-Z_SCORE_CAP, min(Z_SCORE_CAP, (value - mean) / std_dev))
        for symbol, value in values.items()
    }


def _inverse_metric(value: Optional[float]) -> Optional[float]:
    if value is None or value <= 0:
        return None
    return 1.0 / value


def _passes_base_fundamental_filter(snapshot: FundamentalSnapshot, config: Dict[str, Any]) -> bool:
    strategy = config["strategy"]
    thresholds = strategy["thresholds"]
    universe = strategy["universe"]

    if universe.get("require_fundamental_data", True) and not snapshot.has_fundamental_data:
        return False
    if snapshot.market_cap <= float(universe["min_market_cap"]):
        return False
    if snapshot.exchange_id != str(universe["exchange_id"]):
        return False
    if snapshot.price <= float(universe["min_price"]):
        return False
    if snapshot.volume <= 0:
        return False
    if snapshot.gross_margin is None or snapshot.gross_margin < float(thresholds["gross_margin_min"]):
        return False
    if snapshot.debt_to_equity is None:
        return False
    if not float(thresholds["debt_to_equity_min"]) < snapshot.debt_to_equity <= float(thresholds["debt_to_equity_max"]):
        return False
    if snapshot.net_income_growth is not None and snapshot.net_income_growth < 0:
        return False
    if snapshot.pe_ratio is None or snapshot.pe_ratio <= float(thresholds["pe_ratio_min"]):
        return False
    if snapshot.peg_ratio is None:
        return False
    if not float(thresholds["peg_ratio_min"]) < snapshot.peg_ratio <= float(thresholds["peg_ratio_max"]):
        return False
    return True


def _percentile_by_symbol(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    if len(values) == 1:
        symbol = next(iter(values))
        return {symbol: 1.0}

    sorted_items = sorted(values.items(), key=lambda item: (item[1], item[0]))
    indexes_by_value: Dict[float, List[int]] = defaultdict(list)
    for index, (_, value) in enumerate(sorted_items):
        indexes_by_value[value].append(index)

    denominator = len(sorted_items) - 1
    percentiles: Dict[str, float] = {}
    for symbol, value in sorted_items:
        positions = indexes_by_value[value]
        average_index = (positions[0] + positions[-1]) / 2
        percentiles[symbol] = average_index / denominator if denominator > 0 else 1.0
    return percentiles


def _build_sector_percentiles(
    snapshots: Iterable[FundamentalSnapshot],
    metric_names: Iterable[str] = SECTOR_RELATIVE_METRICS,
) -> Dict[str, Dict[str, float]]:
    sector_groups: Dict[str, Dict[str, Dict[str, float]]] = {
        metric: defaultdict(dict) for metric in metric_names
    }
    for snapshot in snapshots:
        if not snapshot.sector_code:
            continue
        for metric in metric_names:
            value = getattr(snapshot, metric)
            if value is None:
                continue
            sector_groups[metric][snapshot.sector_code][snapshot.symbol] = float(value)

    percentiles: Dict[str, Dict[str, float]] = {metric: {} for metric in metric_names}
    for metric, grouped_values in sector_groups.items():
        for values_by_symbol in grouped_values.values():
            percentiles[metric].update(_percentile_by_symbol(values_by_symbol))
    return percentiles


def passes_fundamental_filter(
    snapshot: FundamentalSnapshot,
    config: Dict[str, Any],
    sector_percentiles: Optional[Dict[str, Dict[str, float]]] = None,
) -> bool:
    """Return True when a symbol qualifies for ranking."""

    if not _passes_base_fundamental_filter(snapshot, config):
        return False

    thresholds = config["strategy"]["thresholds"]
    if not sector_percentiles or not snapshot.sector_code:
        if snapshot.roe is None or snapshot.roe < float(thresholds["roe_min"]):
            return False
        if snapshot.revenue_growth is None or snapshot.revenue_growth < float(thresholds["revenue_growth_min"]):
            return False
        if not tolerate_missing_net_income_growth(snapshot.net_income_growth):
            if snapshot.net_income_growth < float(thresholds["net_income_growth_min"]):
                return False
        return True

    percentile_floor = float(thresholds.get("sector_percentile_min", 0.7))
    symbol = snapshot.symbol
    if snapshot.roe is None or sector_percentiles.get("roe", {}).get(symbol, -1.0) < percentile_floor:
        return False
    if snapshot.revenue_growth is None or sector_percentiles.get("revenue_growth", {}).get(symbol, -1.0) < percentile_floor:
        return False
    if not tolerate_missing_net_income_growth(snapshot.net_income_growth):
        if sector_percentiles.get("net_income_growth", {}).get(symbol, -1.0) < percentile_floor:
            return False
    return True


def rank_fundamental_candidates(
    snapshots: Iterable[FundamentalSnapshot],
    config: Dict[str, Any],
    *,
    already_filtered: bool = False,
) -> List[RankedCandidate]:
    """Rank the eligible universe using weighted capped z-score factors."""

    base_eligible = [snapshot for snapshot in snapshots if _passes_base_fundamental_filter(snapshot, config)]
    if not base_eligible:
        return []

    if already_filtered:
        eligible = list(base_eligible)
        sector_percentiles: Dict[str, Dict[str, float]] = {}
    else:
        sector_percentiles = _build_sector_percentiles(base_eligible)
        eligible = [
            snapshot
            for snapshot in base_eligible
            if passes_fundamental_filter(snapshot, config, sector_percentiles=sector_percentiles)
        ]
    if not eligible:
        return []

    weights = config["strategy"]["weights"]
    normalized_roe = _normalize_by_symbol(
        {snapshot.symbol: snapshot.roe or 0.0 for snapshot in eligible if snapshot.roe is not None}
    )
    normalized_revenue_growth = _normalize_by_symbol(
        {
            snapshot.symbol: snapshot.revenue_growth or 0.0
            for snapshot in eligible
            if snapshot.revenue_growth is not None
        }
    )
    normalized_net_income_growth = _normalize_by_symbol(
        {
            snapshot.symbol: snapshot.net_income_growth or 0.0
            for snapshot in eligible
            if snapshot.net_income_growth is not None and snapshot.net_income_growth > 0
        }
    )
    normalized_inverse_peg = _normalize_by_symbol(
        {
            snapshot.symbol: inverse_peg
            for snapshot in eligible
            if (inverse_peg := _inverse_metric(snapshot.peg_ratio)) is not None
        }
    )

    ranked = []  # type: List[RankedCandidate]
    for snapshot in eligible:
        roe_percentile = sector_percentiles.get("roe", {}).get(snapshot.symbol)
        revenue_percentile = sector_percentiles.get("revenue_growth", {}).get(snapshot.symbol)
        income_percentile = sector_percentiles.get("net_income_growth", {}).get(snapshot.symbol)
        reasons = [
            f"sector_code={snapshot.sector_code}",
            f"roe={snapshot.roe}",
            f"revenue_growth={snapshot.revenue_growth}",
            f"net_income_growth={snapshot.net_income_growth}",
            f"peg_ratio={snapshot.peg_ratio}",
        ]
        if roe_percentile is not None:
            reasons.append(f"sector_roe_percentile={round(roe_percentile, 4)}")
        if revenue_percentile is not None:
            reasons.append(f"sector_revenue_percentile={round(revenue_percentile, 4)}")
        if income_percentile is not None:
            reasons.append(f"sector_income_percentile={round(income_percentile, 4)}")

        score = (
            normalized_roe.get(snapshot.symbol, 0.0) * float(weights["roe"])
            + normalized_revenue_growth.get(snapshot.symbol, 0.0) * float(weights["revenue_growth"])
            + normalized_net_income_growth.get(snapshot.symbol, 0.0) * float(weights["net_income_growth"])
            + normalized_inverse_peg.get(snapshot.symbol, 0.0) * float(weights["inverse_peg"])
        )
        ranked.append(
            RankedCandidate(
                symbol=snapshot.symbol,
                fundamental_score=round(score, 6),
                reasons=reasons,
            )
        )

    ranked.sort(key=lambda candidate: (-candidate.fundamental_score, candidate.symbol))
    return ranked


def calculate_relative_volume(volumes: Sequence[float], window: int) -> float:
    """Latest volume divided by the trailing average of prior volumes."""

    if len(volumes) < window:
        return 0.0
    lookback = np.asarray(volumes[-window:], dtype=float)
    prior = lookback[:-1]
    average = float(np.mean(prior)) if prior.size else 0.0
    if average <= 0:
        return 0.0
    return float(lookback[-1] / average)


def calculate_sma(prices: Sequence[float], window: int) -> float:
    """Simple moving average over the requested window."""

    if len(prices) < window:
        return 0.0
    return float(np.mean(np.asarray(prices[-window:], dtype=float)))


def calculate_volatility_ratio(prices: Sequence[float], window: int) -> float:
    """Recent volatility divided by prior volatility for a fixed rolling window."""

    if len(prices) < window:
        return 1.0
    series = np.asarray(prices[-window:], dtype=float)
    returns = np.diff(series) / series[:-1]
    if returns.size < 4:
        return 1.0
    midpoint = returns.size // 2
    prior = returns[:midpoint]
    recent = returns[midpoint:]
    prior_vol = float(np.std(prior))
    recent_vol = float(np.std(recent))
    if prior_vol <= 0:
        return 1.0
    return recent_vol / prior_vol


def build_timing_features(
    symbol: str,
    closes: Sequence[float],
    volumes: Sequence[float],
    config: Dict[str, Any],
    last_updated: Optional[datetime] = None,
) -> TimingFeatures:
    """Compute the full timing state used for the combined score."""

    timing = config["strategy"]["timing"]
    weights = config["strategy"]["weights"]
    relative_volume = calculate_relative_volume(volumes, int(timing["volume_window"]))
    volatility_ratio = calculate_volatility_ratio(closes, int(timing["price_window"]))
    short_sma = calculate_sma(closes, int(timing["short_sma"]))
    long_sma = calculate_sma(closes, int(timing["long_sma"]))

    trend_up = short_sma > long_sma > 0
    volatility_contraction = volatility_ratio <= float(timing["volatility_contraction_threshold"])

    score = 0.0
    if relative_volume > float(timing["relative_volume_threshold"]):
        score += float(weights["timing_relative_volume"])
    if volatility_contraction:
        score += float(weights["timing_volatility_contraction"])
    if trend_up:
        score += float(weights["timing_trend"])

    return TimingFeatures(
        symbol=symbol,
        relative_volume=round(relative_volume, 6),
        volatility_ratio=round(volatility_ratio, 6),
        short_sma=round(short_sma, 6),
        long_sma=round(long_sma, 6),
        trend_up=trend_up,
        volatility_contraction=volatility_contraction,
        timing_score=round(score, 6),
        last_updated=last_updated or datetime.now(UTC),
    )


def _allocation_weights(selected: List[RankedCandidate]) -> Dict[str, float]:
    if not selected:
        return {}
    minimum_score = min(candidate.combined_score for candidate in selected)
    offset = (-minimum_score + 1e-6) if minimum_score <= 0 else 0.0
    bases = {candidate.symbol: candidate.combined_score + offset for candidate in selected}
    total = sum(bases.values())
    if total <= 0:
        equal_weight = 1.0 / len(selected)
        return {candidate.symbol: equal_weight for candidate in selected}

    weights = {}  # type: Dict[str, float]
    allocated = 0.0
    for candidate in selected[:-1]:
        weight = bases[candidate.symbol] / total
        weights[candidate.symbol] = weight
        allocated += weight
    weights[selected[-1].symbol] = max(0.0, 1.0 - allocated)
    return weights


def combine_candidate_scores(
    ranked_candidates: Iterable[RankedCandidate],
    timing_map: Dict[str, TimingFeatures],
    config: Dict[str, Any],
) -> List[RankedCandidate]:
    """Combine fundamental and timing scores, then assign conviction-weighted targets."""

    weights = config["strategy"]["weights"]
    rebalance = config["strategy"]["rebalance"]
    pool_size = int(rebalance["max_holdings"]) * int(rebalance["candidate_pool_multiplier"])
    pool = list(ranked_candidates)[:pool_size]
    combined = []  # type: List[RankedCandidate]
    for candidate in pool:
        timing = timing_map.get(candidate.symbol)
        timing_score = timing.timing_score if timing else 0.0
        total = (
            candidate.fundamental_score * float(weights["fundamental_component"])
            + timing_score * float(weights["timing_component"])
        )
        combined.append(
            RankedCandidate(
                symbol=candidate.symbol,
                fundamental_score=candidate.fundamental_score,
                timing_score=round(timing_score, 6),
                combined_score=round(total, 6),
                reasons=list(candidate.reasons),
            )
        )

    combined.sort(key=lambda candidate: (-candidate.combined_score, candidate.symbol))
    selected = combined[: int(rebalance["max_holdings"])]
    allocation = _allocation_weights(selected)
    if selected:
        updated_selected = []
        for candidate in selected:
            updated_selected.append(
                RankedCandidate(
                    symbol=candidate.symbol,
                    fundamental_score=candidate.fundamental_score,
                    timing_score=candidate.timing_score,
                    combined_score=candidate.combined_score,
                    target_weight=allocation.get(candidate.symbol, 0.0),
                    reasons=list(candidate.reasons),
                )
            )
        combined = updated_selected + combined[len(selected) :]
    return combined


def build_rebalance_intent(
    rebalance_key: str,
    snapshots: Iterable[FundamentalSnapshot],
    timing_map: Dict[str, TimingFeatures],
    config: Dict[str, Any],
    *,
    already_filtered: bool = False,
) -> RebalanceIntent:
    """Build a deterministic rebalance intent from fundamentals and timing state."""

    ranked = rank_fundamental_candidates(snapshots, config, already_filtered=already_filtered)
    combined = combine_candidate_scores(ranked, timing_map, config)
    max_holdings = int(config["strategy"]["rebalance"]["max_holdings"])
    selected = combined[:max_holdings]
    targets = {candidate.symbol: candidate.target_weight for candidate in selected}
    return RebalanceIntent(
        rebalance_key=rebalance_key,
        selected_symbols=[candidate.symbol for candidate in selected],
        target_weights=targets,
        scored_candidates=combined,
        metadata={
            "candidate_pool_size": len(combined),
            "max_holdings": max_holdings,
            "allocation_mode": "combined_score_weighted",
            "already_filtered": already_filtered,
        },
    )


def hash_rebalance_intent(intent: RebalanceIntent) -> str:
    """Return a stable hash for idempotency and regression checks."""

    payload = {
        "rebalance_key": intent.rebalance_key,
        "selected_symbols": intent.selected_symbols,
        "target_weights": intent.target_weights,
        "scored_candidates": [asdict(candidate) for candidate in intent.scored_candidates],
        "metadata": intent.metadata,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stale_data_detected(
    last_updated: Optional[datetime],
    max_age_minutes: int,
    now: Optional[datetime] = None,
    max_age_days: int = 4,
) -> bool:
    """Return True when data is missing or older than the allowed freshness window."""

    if last_updated is None:
        return True
    reference = now or datetime.now(UTC)
    if last_updated >= reference - timedelta(minutes=max_age_minutes):
        return False
    return last_updated.date() < (reference.date() - timedelta(days=max_age_days))
