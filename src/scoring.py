"""Pure scoring logic for the quality-growth strategy."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Iterable

from src.models import (
    FundamentalSnapshot,
    LLMMode,
    RankedCandidate,
    RebalanceIntent,
    StrategyParameters,
    TimingFeatures,
)


Z_SCORE_CAP = 3.0
SECTOR_RELATIVE_METRICS = ("roe", "revenue_growth", "net_income_growth")


def _normalize_by_symbol(values: dict[str, float]) -> dict[str, float]:
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


def _inverse_metric(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return 1.0 / value


def _passes_base_fundamental_filter(snapshot: FundamentalSnapshot, strategy: StrategyParameters) -> bool:
    thresholds = strategy.thresholds
    universe = strategy.universe

    if universe.require_fundamental_data and not snapshot.has_fundamental_data:
        return False
    if snapshot.market_cap <= universe.min_market_cap:
        return False
    if snapshot.exchange_id != universe.exchange_id:
        return False
    if snapshot.price <= universe.min_price:
        return False
    if snapshot.volume <= 0:
        return False
    if snapshot.gross_margin is None or snapshot.gross_margin < thresholds.gross_margin_min:
        return False
    if snapshot.debt_to_equity is None:
        return False
    if not thresholds.debt_to_equity_min < snapshot.debt_to_equity <= thresholds.debt_to_equity_max:
        return False
    if snapshot.net_income_growth is not None and snapshot.net_income_growth < 0:
        return False
    if snapshot.pe_ratio is None or snapshot.pe_ratio <= thresholds.pe_ratio_min:
        return False
    if snapshot.peg_ratio is None:
        return False
    if not thresholds.peg_ratio_min < snapshot.peg_ratio <= thresholds.peg_ratio_max:
        return False
    return True


def _percentile_by_symbol(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    if len(values) == 1:
        symbol = next(iter(values))
        return {symbol: 1.0}

    sorted_items = sorted(values.items(), key=lambda item: (item[1], item[0]))
    indexes_by_value: dict[float, list[int]] = defaultdict(list)
    for index, (_, value) in enumerate(sorted_items):
        indexes_by_value[value].append(index)

    denominator = len(sorted_items) - 1
    percentiles: dict[str, float] = {}
    for symbol, value in sorted_items:
        positions = indexes_by_value[value]
        average_index = (positions[0] + positions[-1]) / 2
        percentiles[symbol] = average_index / denominator if denominator > 0 else 1.0
    return percentiles


def _build_sector_percentiles(
    snapshots: Iterable[FundamentalSnapshot],
    metric_names: Iterable[str] = SECTOR_RELATIVE_METRICS,
) -> dict[str, dict[str, float]]:
    sector_groups: dict[str, dict[str, dict[str, float]]] = {
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

    percentiles: dict[str, dict[str, float]] = {metric: {} for metric in metric_names}
    for metric, grouped_values in sector_groups.items():
        for values_by_symbol in grouped_values.values():
            percentiles[metric].update(_percentile_by_symbol(values_by_symbol))
    return percentiles


def tolerate_missing_net_income_growth(value: float | None) -> bool:
    """Mirror the adjusted strategy's permissive handling for missing or zero values."""

    return value is None or value == 0


def passes_fundamental_filter(
    snapshot: FundamentalSnapshot,
    strategy: StrategyParameters,
    sector_percentiles: dict[str, dict[str, float]] | None = None,
) -> bool:
    """Return True when a symbol qualifies for ranking."""

    if not _passes_base_fundamental_filter(snapshot, strategy):
        return False

    thresholds = strategy.thresholds
    if not sector_percentiles or not snapshot.sector_code:
        if snapshot.roe is None or snapshot.roe < thresholds.roe_min:
            return False
        if snapshot.revenue_growth is None or snapshot.revenue_growth < thresholds.revenue_growth_min:
            return False
        if not tolerate_missing_net_income_growth(snapshot.net_income_growth):
            if snapshot.net_income_growth < thresholds.net_income_growth_min:
                return False
        return True

    percentile_floor = thresholds.sector_percentile_min
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
    strategy: StrategyParameters,
    *,
    already_filtered: bool = False,
) -> list[RankedCandidate]:
    """Rank the eligible universe using weighted capped z-score factors."""

    base_eligible = [snapshot for snapshot in snapshots if _passes_base_fundamental_filter(snapshot, strategy)]
    if not base_eligible:
        return []

    if already_filtered:
        eligible = list(base_eligible)
        sector_percentiles: dict[str, dict[str, float]] = {}
    else:
        sector_percentiles = _build_sector_percentiles(base_eligible)
        eligible = [
            snapshot
            for snapshot in base_eligible
            if passes_fundamental_filter(snapshot, strategy, sector_percentiles=sector_percentiles)
        ]
    if not eligible:
        return []

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

    weights = strategy.weights
    ranked: list[RankedCandidate] = []
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
            normalized_roe.get(snapshot.symbol, 0.0) * weights.roe
            + normalized_revenue_growth.get(snapshot.symbol, 0.0) * weights.revenue_growth
            + normalized_net_income_growth.get(snapshot.symbol, 0.0) * weights.net_income_growth
            + normalized_inverse_peg.get(snapshot.symbol, 0.0) * weights.inverse_peg
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


def _allocation_weights(selected: list[RankedCandidate]) -> dict[str, float]:
    if not selected:
        return {}
    minimum_score = min(candidate.combined_score for candidate in selected)
    offset = (-minimum_score + 1e-6) if minimum_score <= 0 else 0.0
    bases = {candidate.symbol: candidate.combined_score + offset for candidate in selected}
    total = sum(bases.values())
    if total <= 0:
        equal_weight = 1.0 / len(selected)
        return {candidate.symbol: equal_weight for candidate in selected}

    weights: dict[str, float] = {}
    allocated = 0.0
    for candidate in selected[:-1]:
        weight = bases[candidate.symbol] / total
        weights[candidate.symbol] = weight
        allocated += weight
    weights[selected[-1].symbol] = max(0.0, 1.0 - allocated)
    return weights


def combine_candidate_scores(
    ranked_candidates: Iterable[RankedCandidate],
    timing_map: dict[str, TimingFeatures],
    strategy: StrategyParameters,
) -> list[RankedCandidate]:
    """Combine fundamental and timing scores, then assign conviction-weighted targets."""

    weights = strategy.weights
    pool_size = strategy.rebalance.max_holdings * strategy.rebalance.candidate_pool_multiplier
    pool = list(ranked_candidates)[:pool_size]
    combined: list[RankedCandidate] = []
    for candidate in pool:
        timing = timing_map.get(candidate.symbol)
        timing_score = timing.timing_score if timing else 0.0
        total = candidate.fundamental_score * weights.fundamental_component + timing_score * weights.timing_component
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
    selected = combined[: strategy.rebalance.max_holdings]
    allocation = _allocation_weights(selected)
    for candidate in selected:
        candidate.target_weight = allocation.get(candidate.symbol, 0.0)
    return combined


def build_rebalance_intent(
    rebalance_key: str,
    snapshots: Iterable[FundamentalSnapshot],
    timing_map: dict[str, TimingFeatures],
    strategy: StrategyParameters,
    *,
    already_filtered: bool = False,
) -> RebalanceIntent:
    """Build a deterministic rebalance intent from fundamentals and timing state."""

    ranked = rank_fundamental_candidates(snapshots, strategy, already_filtered=already_filtered)
    combined = combine_candidate_scores(ranked, timing_map, strategy)
    selected = combined[: strategy.rebalance.max_holdings]
    targets = {candidate.symbol: candidate.target_weight for candidate in selected}
    return RebalanceIntent(
        rebalance_key=rebalance_key,
        selected_symbols=[candidate.symbol for candidate in selected],
        target_weights=targets,
        scored_candidates=combined,
        llm_policy_mode=LLMMode.OBSERVE_ONLY,
        metadata={
            "candidate_pool_size": len(combined),
            "max_holdings": strategy.rebalance.max_holdings,
            "allocation_mode": "combined_score_weighted",
            "already_filtered": already_filtered,
        },
    )


def hash_rebalance_intent(intent: RebalanceIntent) -> str:
    """Return a stable hash for idempotency and regression checks."""

    payload = intent.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
