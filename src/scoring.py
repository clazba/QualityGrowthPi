"""Pure scoring logic for the quality-growth strategy."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from src.models import FundamentalSnapshot, LLMMode, RankedCandidate, RebalanceIntent, StrategyParameters, TimingFeatures


def _normalize_by_symbol(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    minimum = min(values.values())
    maximum = max(values.values())
    if minimum == maximum:
        return {symbol: 1.0 for symbol in values}
    spread = maximum - minimum
    return {symbol: (value - minimum) / spread for symbol, value in values.items()}


def _inverse_metric(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return 1.0 / value


def tolerate_missing_net_income_growth(value: float | None) -> bool:
    """Mirror the adjusted strategy's permissive handling for missing or zero values."""

    return value is None or value == 0


def passes_fundamental_filter(snapshot: FundamentalSnapshot, strategy: StrategyParameters) -> bool:
    """Return True when a symbol qualifies for ranking."""

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
    if snapshot.roe is None or snapshot.roe < thresholds.roe_min:
        return False
    if snapshot.gross_margin is None or snapshot.gross_margin < thresholds.gross_margin_min:
        return False
    if snapshot.debt_to_equity is None:
        return False
    if not thresholds.debt_to_equity_min < snapshot.debt_to_equity <= thresholds.debt_to_equity_max:
        return False
    if snapshot.revenue_growth is None or snapshot.revenue_growth < thresholds.revenue_growth_min:
        return False
    if snapshot.net_income_growth is not None and snapshot.net_income_growth < 0:
        return False
    if not tolerate_missing_net_income_growth(snapshot.net_income_growth):
        if snapshot.net_income_growth < thresholds.net_income_growth_min:
            return False
    if snapshot.pe_ratio is None or snapshot.pe_ratio <= thresholds.pe_ratio_min:
        return False
    if snapshot.peg_ratio is None:
        return False
    if not thresholds.peg_ratio_min < snapshot.peg_ratio <= thresholds.peg_ratio_max:
        return False
    return True


def rank_fundamental_candidates(
    snapshots: Iterable[FundamentalSnapshot],
    strategy: StrategyParameters,
) -> list[RankedCandidate]:
    """Rank the eligible universe using weighted normalized fundamental factors."""

    eligible = [snapshot for snapshot in snapshots if passes_fundamental_filter(snapshot, strategy)]
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
        reasons = [
            f"roe={snapshot.roe}",
            f"revenue_growth={snapshot.revenue_growth}",
            f"net_income_growth={snapshot.net_income_growth}",
            f"peg_ratio={snapshot.peg_ratio}",
        ]
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


def combine_candidate_scores(
    ranked_candidates: Iterable[RankedCandidate],
    timing_map: dict[str, TimingFeatures],
    strategy: StrategyParameters,
) -> list[RankedCandidate]:
    """Combine fundamental and timing scores, then assign equal weights to final selections."""

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
    if selected:
        weight = 1.0 / len(selected)
        for candidate in selected:
            candidate.target_weight = weight
    return combined


def build_rebalance_intent(
    rebalance_key: str,
    snapshots: Iterable[FundamentalSnapshot],
    timing_map: dict[str, TimingFeatures],
    strategy: StrategyParameters,
) -> RebalanceIntent:
    """Build a deterministic rebalance intent from fundamentals and timing state."""

    ranked = rank_fundamental_candidates(snapshots, strategy)
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
        },
    )


def hash_rebalance_intent(intent: RebalanceIntent) -> str:
    """Return a stable hash for idempotency and regression checks."""

    payload = intent.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
