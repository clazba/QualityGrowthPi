"""Unit tests for stat-arb sizing and exit logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.models import MLTradeFilterDecision, PairCandidate, PairPositionState, SpreadFeatures
from src.settings import load_settings
from src.stat_arb.risk import build_pair_trade_intents, decayed_exit_thresholds, evaluate_pair_exit


def _candidate(z_score: float) -> PairCandidate:
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
            correlation=0.88,
            correlation_stability=0.77,
            current_spread=0.4,
            spread_mean=0.0,
            spread_std=0.2,
            z_score=z_score,
            mean_reversion_speed=0.16,
            half_life_days=5.0,
            transaction_cost_bps=5.0,
            expected_edge_bps=44.0,
            last_updated=datetime.now(UTC),
        ),
    )


def test_decayed_exit_thresholds_tighten_over_time() -> None:
    settings = load_settings()
    fresh_stop, fresh_take = decayed_exit_thresholds(0.0, settings.stat_arb)
    aged_stop, aged_take = decayed_exit_thresholds(10.0, settings.stat_arb)

    assert aged_stop < fresh_stop
    assert aged_take < fresh_take


def test_build_pair_trade_intents_applies_kelly_and_neutral_weights() -> None:
    settings = load_settings()
    candidate = _candidate(z_score=2.0)
    decision = MLTradeFilterDecision(
        pair_id=candidate.pair_id,
        cluster_id=candidate.cluster_id,
        execute=True,
        predicted_win_probability=0.66,
        confidence_score=0.72,
        expected_edge_bps=44.0,
        vote_ratio=0.8,
        model_version="ensemble_v1",
        rationale="fixture",
    )

    intents = build_pair_trade_intents(
        [candidate],
        {candidate.pair_id: decision},
        settings.stat_arb,
        portfolio_equity=100_000.0,
        open_positions=[],
    )

    assert len(intents) == 1
    assert intents[0].long_weight == -intents[0].short_weight
    assert intents[0].kelly_fraction > 0


def test_evaluate_pair_exit_fires_time_exit() -> None:
    settings = load_settings()
    opened_at = datetime.now(UTC) - timedelta(days=settings.stat_arb.exit_policy.max_holding_days + 1)
    state = PairPositionState(
        pair_id="cluster_001:AAPL:MSFT",
        cluster_id="cluster_001",
        long_symbol="AAPL",
        short_symbol="MSFT",
        opened_at=opened_at,
        entry_z_score=2.1,
        latest_z_score=1.7,
        hedge_ratio=1.0,
        gross_exposure=0.08,
        net_exposure=0.0,
        kelly_fraction=0.08,
        stop_loss_z_score=3.25,
        take_profit_z_score=0.35,
        max_holding_days=settings.stat_arb.exit_policy.max_holding_days,
    )

    exit_signal = evaluate_pair_exit(state, _candidate(z_score=1.4), settings.stat_arb, datetime.now(UTC))

    assert exit_signal["should_exit"] is True
    assert exit_signal["reason"] == "time_exit"
