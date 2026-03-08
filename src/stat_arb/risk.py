"""Position sizing and exit logic for stat-arb pairs."""

from __future__ import annotations

from datetime import UTC, datetime

from src.models import (
    MLTradeFilterDecision,
    PairCandidate,
    PairPositionState,
    PairTradeIntent,
    StatArbSettings,
)


def decayed_exit_thresholds(
    days_open: float,
    settings: StatArbSettings,
) -> tuple[float, float]:
    """Return decayed stop-loss and take-profit thresholds."""

    policy = settings.exit_policy
    decay_factor = 0.5 ** (max(days_open, 0.0) / policy.decay_half_life_days)
    stop_loss = policy.minimum_stop_loss_z_score + (
        policy.initial_stop_loss_z_score - policy.minimum_stop_loss_z_score
    ) * decay_factor
    take_profit = policy.minimum_take_profit_z_score + (
        policy.initial_take_profit_z_score - policy.minimum_take_profit_z_score
    ) * decay_factor
    return round(stop_loss, 6), round(take_profit, 6)


def evaluate_pair_exit(
    state: PairPositionState,
    candidate: PairCandidate | None,
    settings: StatArbSettings,
    as_of: datetime,
) -> dict[str, object]:
    """Evaluate whether an open pair should be closed."""

    elapsed_days = max(0.0, (as_of.astimezone(UTC) - state.opened_at.astimezone(UTC)).total_seconds() / 86_400.0)
    stop_loss_z, take_profit_z = decayed_exit_thresholds(elapsed_days, settings)
    current_z = candidate.spread_features.z_score if candidate is not None else state.latest_z_score

    reason = "hold"
    should_exit = False
    if abs(current_z) <= take_profit_z:
        should_exit = True
        reason = "take_profit"
    elif abs(current_z) >= stop_loss_z:
        should_exit = True
        reason = "stop_loss"
    elif elapsed_days >= settings.exit_policy.max_holding_days:
        should_exit = True
        reason = "time_exit"
    elif candidate is None:
        should_exit = True
        reason = "signal_unavailable"

    return {
        "pair_id": state.pair_id,
        "should_exit": should_exit,
        "reason": reason,
        "stop_loss_z_score": stop_loss_z,
        "take_profit_z_score": take_profit_z,
        "current_z_score": round(current_z, 6),
        "elapsed_days": round(elapsed_days, 6),
    }


def _kelly_fraction(
    decision: MLTradeFilterDecision,
    settings: StatArbSettings,
) -> float:
    sizing = settings.sizing
    if not decision.execute or decision.predicted_win_probability < sizing.probability_floor:
        return 0.0
    payoff_ratio = max(sizing.payoff_ratio_floor, decision.expected_edge_bps / 25.0)
    probability = decision.predicted_win_probability
    raw_fraction = probability - ((1.0 - probability) / payoff_ratio)
    scaled_fraction = max(0.0, raw_fraction) * decision.confidence_score
    return min(sizing.max_fraction, max(sizing.min_fraction, scaled_fraction))


def build_pair_trade_intents(
    candidates: list[PairCandidate],
    decisions: dict[str, MLTradeFilterDecision],
    settings: StatArbSettings,
    portfolio_equity: float,
    open_positions: list[PairPositionState] | None = None,
) -> list[PairTradeIntent]:
    """Size accepted pair trades with Kelly fractions and overlap caps."""

    sizing = settings.sizing
    open_positions = open_positions or []
    open_pairs_count = len([state for state in open_positions if state.status == "open"])
    if open_pairs_count >= sizing.max_open_pairs:
        return []

    open_symbols = {
        symbol
        for state in open_positions
        if state.status == "open"
        for symbol in (state.long_symbol, state.short_symbol)
    }
    cluster_counts: dict[str, int] = {}
    total_gross = sum(abs(state.gross_exposure) for state in open_positions if state.status == "open")
    total_net = sum(state.net_exposure for state in open_positions if state.status == "open")

    intents: list[PairTradeIntent] = []
    for candidate in candidates:
        decision = decisions.get(candidate.pair_id)
        if decision is None or not decision.execute:
            continue
        if len(intents) + open_pairs_count >= sizing.max_open_pairs:
            break
        if cluster_counts.get(candidate.cluster_id, 0) >= sizing.max_pairs_per_cluster:
            continue
        overlap_multiplier = 1.0
        if candidate.first_symbol in open_symbols or candidate.second_symbol in open_symbols:
            overlap_multiplier -= sizing.overlap_penalty
        kelly_fraction = _kelly_fraction(decision, settings) * max(overlap_multiplier, 0.0)
        if kelly_fraction <= 0:
            continue

        gross_exposure = min(
            portfolio_equity * kelly_fraction,
            portfolio_equity * sizing.max_gross_exposure_per_trade,
            max(0.0, (portfolio_equity * sizing.max_gross_exposure_total) - total_gross),
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
        if abs(total_net + net_exposure) > sizing.max_net_exposure_total:
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
                metadata={
                    "first_symbol": candidate.first_symbol,
                    "second_symbol": candidate.second_symbol,
                    "overlap_multiplier": round(overlap_multiplier, 6),
                },
            )
        )
        cluster_counts[candidate.cluster_id] = cluster_counts.get(candidate.cluster_id, 0) + 1
        total_gross += abs(intents[-1].gross_exposure)
        total_net += net_exposure
        open_symbols.update({candidate.first_symbol, candidate.second_symbol})
    return intents
