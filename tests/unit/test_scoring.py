"""Unit tests for fundamental ranking and deterministic rebalance intent generation."""

import pytest

from src.models import FundamentalSnapshot, TimingFeatures
from src.scoring import build_rebalance_intent, passes_fundamental_filter, rank_fundamental_candidates
from src.settings import load_settings


def _snapshot(
    symbol: str,
    roe: float,
    revenue_growth: float,
    net_income_growth,
    peg_ratio: float,
    *,
    sector_code: str | None = None,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        market_cap=2_000_000_000,
        exchange_id="NYS",
        price=25.0,
        volume=100_000,
        sector_code=sector_code,
        roe=roe,
        gross_margin=0.45,
        debt_to_equity=0.5,
        revenue_growth=revenue_growth,
        net_income_growth=net_income_growth,
        pe_ratio=18.0,
        peg_ratio=peg_ratio,
    )


def test_missing_net_income_growth_is_tolerated() -> None:
    settings = load_settings()
    snapshot = _snapshot("AAA", 0.20, 0.18, None, 1.2)
    assert passes_fundamental_filter(snapshot, settings.strategy)


def test_rank_fundamental_candidates_orders_highest_score_first() -> None:
    settings = load_settings()
    ranked = rank_fundamental_candidates(
        [
            _snapshot("AAA", 0.30, 0.25, 0.20, 0.8),
            _snapshot("BBB", 0.24, 0.20, 0.18, 1.1),
            _snapshot("CCC", 0.18, 0.15, 0.0, 1.9),
        ],
        settings.strategy,
    )
    assert [candidate.symbol for candidate in ranked] == ["AAA", "BBB", "CCC"]


def test_build_rebalance_intent_assigns_score_weighted_holdings() -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "rebalance": settings.strategy.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )
    snapshots = [
        _snapshot("AAA", 0.30, 0.25, 0.20, 0.8),
        _snapshot("BBB", 0.28, 0.24, 0.19, 0.9),
        _snapshot("CCC", 0.26, 0.23, 0.18, 1.0),
        _snapshot("DDD", 0.24, 0.22, 0.17, 1.1),
    ]
    timing_map = {
        symbol: TimingFeatures(symbol=symbol, timing_score=0.0)
        for symbol in ["AAA", "BBB", "CCC", "DDD"]
    }
    intent = build_rebalance_intent("2026-03", snapshots, timing_map, strategy)
    assert intent.selected_symbols == ["AAA", "BBB", "CCC"]
    assert sum(intent.target_weights.values()) == pytest.approx(1.0)
    assert intent.target_weights["AAA"] > intent.target_weights["BBB"] > intent.target_weights["CCC"]
    assert len(set(intent.target_weights.values())) == 3


def test_rank_fundamental_candidates_uses_sector_relative_thresholds() -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "thresholds": settings.strategy.thresholds.model_copy(
                update={
                    "roe_min": 0.30,
                    "revenue_growth_min": 0.30,
                    "net_income_growth_min": 0.30,
                    "sector_percentile_min": 0.5,
                }
            )
        }
    )

    ranked = rank_fundamental_candidates(
        [
            _snapshot("AAA", 0.14, 0.16, 0.12, 0.8, sector_code="10"),
            _snapshot("AAB", 0.11, 0.11, 0.09, 0.9, sector_code="10"),
            _snapshot("BBB", 0.13, 0.15, 0.11, 0.85, sector_code="20"),
            _snapshot("BBC", 0.10, 0.10, 0.08, 0.95, sector_code="20"),
        ],
        strategy,
    )

    assert [candidate.symbol for candidate in ranked] == ["AAA", "BBB"]
    assert all("sector_roe_percentile=" in " ".join(candidate.reasons) for candidate in ranked)
