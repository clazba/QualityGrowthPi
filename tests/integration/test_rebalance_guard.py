"""Integration tests for rebalance idempotency and restart recovery."""

from pathlib import Path

from src.models import FundamentalSnapshot, TimingFeatures
from src.scoring import build_rebalance_intent, hash_rebalance_intent
from src.settings import load_settings
from src.state_store import StateStore


def _snapshot(symbol: str, offset: int) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        market_cap=2_500_000_000,
        exchange_id="NYS",
        price=25.0 + offset,
        volume=100_000 + offset,
        roe=0.18 + offset / 1000,
        gross_margin=0.40,
        debt_to_equity=0.6,
        revenue_growth=0.15 + offset / 1000,
        net_income_growth=0.12 + offset / 1000,
        pe_ratio=20.0,
        peg_ratio=1.2 + offset / 1000,
    )


def test_rebalance_guard_survives_restart(tmp_path: Path) -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "rebalance": settings.strategy.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )
    snapshots = [_snapshot(symbol, idx) for idx, symbol in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"])]
    timing_map = {snapshot.symbol: TimingFeatures(symbol=snapshot.symbol, timing_score=0.0) for snapshot in snapshots}

    intent = build_rebalance_intent("QualityGrowthPi:2026-03", snapshots, timing_map, strategy)
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    assert store.mark_rebalance_started(intent.rebalance_key, hash_rebalance_intent(intent), metadata={}) is True
    assert store.mark_rebalance_started(intent.rebalance_key, hash_rebalance_intent(intent), metadata={}) is False
    store.close()

    reopened = StateStore(tmp_path / "quant_gpt.db")
    reopened.initialize()
    assert reopened.has_rebalance(intent.rebalance_key) is True
