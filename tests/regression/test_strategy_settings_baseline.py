"""Regression coverage for the centralized strategy settings architecture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import FundamentalSnapshot, StrategyParameters, TimingFeatures
from src.scoring import build_rebalance_intent
from src.strategy_settings import build_runtime_payload, build_strategy_payload, load_strategy_settings


FIXTURES = Path("tests/regression/fixtures")

LEGACY_STRATEGY_PAYLOAD = {
    "algorithm_name": "QualityGrowthPi",
    "benchmark_symbol": "SPY",
    "rebalance": {
        "frequency": "daily",
        "anchor_symbol": "SPY",
        "after_open_minutes": 30,
        "max_holdings": 20,
        "candidate_pool_multiplier": 3,
    },
    "universe": {
        "exchange_id": "NYS",
        "min_market_cap": 1_000_000_000,
        "min_price": 5.0,
        "require_fundamental_data": True,
    },
    "thresholds": {
        "roe_min": 0.15,
        "gross_margin_min": 0.30,
        "debt_to_equity_min": 0.0,
        "debt_to_equity_max": 2.0,
        "revenue_growth_min": 0.10,
        "net_income_growth_min": 0.10,
        "pe_ratio_min": 0.0,
        "peg_ratio_min": 0.0,
        "peg_ratio_max": 2.0,
        "sector_percentile_min": 0.70,
    },
    "weights": {
        "roe": 0.3,
        "revenue_growth": 0.3,
        "net_income_growth": 0.2,
        "inverse_peg": 0.2,
        "fundamental_component": 0.6,
        "timing_component": 0.4,
        "timing_relative_volume": 0.3,
        "timing_volatility_contraction": 0.4,
        "timing_trend": 0.3,
    },
    "timing": {
        "volume_window": 20,
        "price_window": 20,
        "short_sma": 10,
        "long_sma": 30,
        "relative_volume_threshold": 1.2,
        "volatility_contraction_threshold": 0.85,
    },
}

LEGACY_RUNTIME_PAYLOAD = {
    "backtest_start_date": "2018-01-01",
    "initial_cash": 100_000.0,
    "bootstrap_history_days": 35,
    "stale_data_max_age_minutes": 30,
    "fine_universe_limit": 1000,
    "cloud_audit_logging": True,
}


def test_default_strategy_settings_match_legacy_payload() -> None:
    assert build_strategy_payload("default") == LEGACY_STRATEGY_PAYLOAD


def test_default_runtime_settings_match_legacy_payload() -> None:
    assert build_runtime_payload("default") == LEGACY_RUNTIME_PAYLOAD


def test_stat_arb_strategy_payload_exposes_graph_mode() -> None:
    payload = build_strategy_payload("default", "stat_arb_graph_pairs")
    runtime = build_runtime_payload("default", "stat_arb_graph_pairs")

    assert payload["algorithm_name"] == "GraphStatArb"
    assert "graph" in payload
    assert "spread" in payload
    assert "ml_filter" in payload
    assert payload["ml_filter"]["mode"] == "embedded_scorecard"
    assert payload["ml_filter"]["feature_schema_version"] == "stat_arb_v1"
    assert payload["ml_filter"]["fallback_mode"] == "embedded_scorecard"
    assert runtime["backtest_start_date"] == "2022-01-01"
    assert runtime["fine_universe_limit"] == len(payload["universe"]["symbols"])


def test_short_regression_profile_only_shortens_horizon() -> None:
    default_settings = load_strategy_settings("default")
    short_settings = load_strategy_settings("short_regression")

    assert short_settings.to_strategy_payload() == default_settings.to_strategy_payload()
    assert short_settings.to_runtime_payload() == {
        **default_settings.to_runtime_payload(),
        "backtest_start_date": "2025-01-01",
    }


def test_centralized_settings_preserve_legacy_rebalance_math() -> None:
    universe_payload = json.loads((FIXTURES / "universe_snapshot.json").read_text(encoding="utf-8"))
    timing_payload = json.loads((FIXTURES / "timing_snapshot.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "expected_targets.json").read_text(encoding="utf-8"))

    snapshots = [FundamentalSnapshot(**row) for row in universe_payload]
    timing_map = {symbol: TimingFeatures(**payload) for symbol, payload in timing_payload.items()}

    centralized_base = StrategyParameters(**build_strategy_payload("default"))
    centralized_strategy = centralized_base.model_copy(
        update={
            "rebalance": centralized_base.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )
    legacy_base = StrategyParameters(**LEGACY_STRATEGY_PAYLOAD)
    legacy_strategy = legacy_base.model_copy(
        update={
            "rebalance": legacy_base.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )

    centralized_intent = build_rebalance_intent(expected["rebalance_key"], snapshots, timing_map, centralized_strategy)
    legacy_intent = build_rebalance_intent(expected["rebalance_key"], snapshots, timing_map, legacy_strategy)

    assert centralized_intent.selected_symbols == legacy_intent.selected_symbols
    assert centralized_intent.target_weights == pytest.approx(legacy_intent.target_weights)
