"""Regression coverage for robust scoring, sector-relative filtering, and conviction weighting."""

from __future__ import annotations

import pytest

from src.models import FundamentalSnapshot, TimingFeatures
from src.scoring import _normalize_by_symbol, build_rebalance_intent, rank_fundamental_candidates
from src.settings import load_settings


def _snapshot(
    symbol: str,
    *,
    sector_code: str | None,
    roe: float,
    revenue_growth: float,
    net_income_growth: float | None,
    peg_ratio: float,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        sector_code=sector_code,
        market_cap=2_000_000_000,
        exchange_id="NYS",
        price=25.0,
        volume=100_000,
        roe=roe,
        gross_margin=0.45,
        debt_to_equity=0.5,
        revenue_growth=revenue_growth,
        net_income_growth=net_income_growth,
        pe_ratio=18.0,
        peg_ratio=peg_ratio,
    )


def _legacy_min_max(values: dict[str, float]) -> dict[str, float]:
    minimum = min(values.values())
    maximum = max(values.values())
    if maximum == minimum:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (value - minimum) / (maximum - minimum) for symbol, value in values.items()}


def test_robust_z_scores_cap_outliers_without_flattening_cross_section() -> None:
    values = {f"S{i:02d}": float(i) for i in range(1, 11)}
    values["OUT"] = 1_000_000.0

    normalized = _normalize_by_symbol(values)
    legacy = _legacy_min_max(values)

    assert max(abs(value) for value in normalized.values()) <= 3.0
    assert normalized["OUT"] == pytest.approx(3.0)
    assert (normalized["S10"] - normalized["S09"]) > (legacy["S10"] - legacy["S09"])


def test_sector_relative_filtering_survives_absolute_threshold_collapse() -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "thresholds": settings.strategy.thresholds.model_copy(
                update={
                    "roe_min": 0.35,
                    "revenue_growth_min": 0.35,
                    "net_income_growth_min": 0.35,
                    "sector_percentile_min": 0.5,
                }
            )
        }
    )

    ranked = rank_fundamental_candidates(
        [
            _snapshot("AAA", sector_code="10", roe=0.14, revenue_growth=0.16, net_income_growth=0.13, peg_ratio=0.8),
            _snapshot("AAB", sector_code="10", roe=0.10, revenue_growth=0.12, net_income_growth=0.08, peg_ratio=1.1),
            _snapshot("BBB", sector_code="20", roe=0.13, revenue_growth=0.15, net_income_growth=0.12, peg_ratio=0.9),
            _snapshot("BBC", sector_code="20", roe=0.09, revenue_growth=0.10, net_income_growth=0.07, peg_ratio=1.2),
        ],
        strategy,
    )

    assert [candidate.symbol for candidate in ranked] == ["AAA", "BBB"]


def test_rebalance_intent_allocates_by_combined_score_not_equal_weight() -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "rebalance": settings.strategy.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )
    snapshots = [
        _snapshot("AAA", sector_code="10", roe=0.30, revenue_growth=0.25, net_income_growth=0.20, peg_ratio=0.8),
        _snapshot("BBB", sector_code="20", roe=0.28, revenue_growth=0.24, net_income_growth=0.19, peg_ratio=0.9),
        _snapshot("CCC", sector_code="30", roe=0.26, revenue_growth=0.23, net_income_growth=0.18, peg_ratio=1.0),
        _snapshot("DDD", sector_code="40", roe=0.24, revenue_growth=0.22, net_income_growth=0.17, peg_ratio=1.1),
    ]
    timing_map = {
        "AAA": TimingFeatures(symbol="AAA", timing_score=0.7),
        "BBB": TimingFeatures(symbol="BBB", timing_score=0.4),
        "CCC": TimingFeatures(symbol="CCC", timing_score=0.3),
        "DDD": TimingFeatures(symbol="DDD", timing_score=0.2),
    }

    intent = build_rebalance_intent("QualityGrowthPi:2026-03", snapshots, timing_map, strategy)

    assert intent.selected_symbols == ["AAA", "BBB", "CCC"]
    assert sum(intent.target_weights.values()) == pytest.approx(1.0)
    assert intent.target_weights["AAA"] > intent.target_weights["BBB"] > intent.target_weights["CCC"]
    assert intent.metadata["allocation_mode"] == "combined_score_weighted"
