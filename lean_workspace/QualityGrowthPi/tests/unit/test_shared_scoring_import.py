"""LEAN workspace unit coverage for the cloud-safe local scoring module."""

from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path


PROJECT_DIR = Path("lean_workspace/QualityGrowthPi").resolve()


def _load_module(module_name: str, relative_path: str):
    module_path = (PROJECT_DIR / relative_path).resolve()
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_shared_scoring_imports() -> None:
    scoring = _load_module("qgpi_scoring", "scoring.py")
    config = scoring.load_strategy_config(PROJECT_DIR / "config.py")
    ranked = scoring.rank_fundamental_candidates(
        [
            scoring.FundamentalSnapshot(
                symbol="AAA",
                as_of=scoring.datetime.now(scoring.UTC),
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                roe=0.20,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.20,
                net_income_growth=0.15,
                pe_ratio=20,
                peg_ratio=1.5,
            )
        ],
        config,
    )
    assert ranked[0].symbol == "AAA"
    assert scoring.UTC.utcoffset(None).total_seconds() == 0


def test_algorithm_entrypoint_exposes_qcalgorithm_subclass() -> None:
    main_module = _load_module("qgpi_main", "main.py")
    algorithm_cls = getattr(main_module, "QualityGrowthPiAlgorithm")
    base_cls = getattr(main_module, "QCAlgorithm")
    assert issubclass(algorithm_cls, base_cls)


def test_algorithm_source_avoids_obsolete_two_stage_adduniverse() -> None:
    source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    assert "AddUniverse(self.CoarseSelectionFunction, self.FineSelectionFunction)" not in source
    assert "AddUniverse(self.FundamentalSelectionFunction)" in source


def test_rebalance_defers_without_current_fundamentals() -> None:
    main_module = _load_module("qgpi_main_rebalance", "main.py")
    algo = main_module.QualityGrowthPiAlgorithm()
    events = []
    marks = []

    algo.audit_enabled = True
    algo.current_fundamentals = {}
    algo.timing_features = {}
    algo.runtime = {"stale_data_max_age_minutes": 30}
    algo._rebalance_key = lambda: "QualityGrowthPi:2026-03"
    algo._has_completed_rebalance = lambda key: False
    algo._mark_rebalance_completed = lambda key: marks.append(key)
    algo._emit_audit = lambda event_type, payload: events.append((event_type, payload))

    algo.Rebalance()

    assert marks == []
    assert events
    assert events[-1][0] == "rebalance_deferred"
    assert events[-1][1]["reason"] == "no_current_fundamentals"


def test_rebalance_defers_until_target_symbols_have_prices() -> None:
    main_module = _load_module("qgpi_main_pending_prices", "main.py")
    scoring = _load_module("qgpi_scoring_pending_prices", "scoring.py")
    algo = main_module.QualityGrowthPiAlgorithm()
    events = []
    marks = []
    holdings_calls = []

    class _FakeSecurity:
        def __init__(self, price: float, has_data: bool = True, tradable: bool = True) -> None:
            self.Price = price
            self.HasData = has_data
            self.IsTradable = tradable

    now = scoring.datetime(2026, 3, 9, 9, 30, tzinfo=scoring.UTC)
    algo.audit_enabled = True
    algo.config = scoring.load_strategy_config(PROJECT_DIR / "config.py")
    algo.current_fundamentals = {
        "AAA": scoring.FundamentalSnapshot(
            symbol="AAA",
            as_of=now,
            has_fundamental_data=True,
            market_cap=2_000_000_000,
            exchange_id="NYS",
            price=25,
            volume=100_000,
            roe=0.20,
            gross_margin=0.45,
            debt_to_equity=0.5,
            revenue_growth=0.20,
            net_income_growth=0.15,
            pe_ratio=20,
            peg_ratio=1.5,
        )
    }
    algo.timing_features = {
        "AAA": scoring.TimingFeatures(
            symbol="AAA",
            relative_volume=1.3,
            volatility_ratio=0.8,
            short_sma=12,
            long_sma=10,
            trend_up=True,
            volatility_contraction=True,
            timing_score=1.0,
            last_updated=now,
        )
    }
    algo.runtime = {"stale_data_max_age_minutes": 30}
    algo.symbol_registry = {"AAA": "AAA"}
    algo.Securities = {"AAA": _FakeSecurity(price=0.0, has_data=False)}
    algo.Portfolio = {}
    algo._rebalance_key = lambda: "QualityGrowthPi:2026-03"
    algo._has_completed_rebalance = lambda key: False
    algo._mark_rebalance_completed = lambda key: marks.append(key)
    algo._emit_audit = lambda event_type, payload: events.append((event_type, payload))
    algo.SetRuntimeStatistic = lambda key, value: None
    algo.SetHoldings = lambda symbol, weight: holdings_calls.append((symbol, weight))
    main_module.build_rebalance_intent = lambda **_: main_module.RebalanceIntent(
        rebalance_key="QualityGrowthPi:2026-03",
        selected_symbols=["AAA"],
        target_weights={"AAA": 1.0},
        scored_candidates=[],
        metadata={},
    )

    algo.Rebalance()

    assert marks == []
    assert holdings_calls == []
    assert events
    assert events[-1][0] == "rebalance_deferred"
    assert events[-1][1]["reason"] == "pending_prices"
    assert events[-1][1]["symbols"] == ["AAA"]


def test_daily_bar_stale_check_allows_prior_session_data() -> None:
    scoring = _load_module("qgpi_scoring_daily_stale", "scoring.py")
    now = scoring.datetime(2026, 3, 9, 9, 30, tzinfo=scoring.UTC)
    last_updated = scoring.datetime(2026, 3, 6, 16, 0, tzinfo=scoring.UTC)
    assert scoring.stale_data_detected(last_updated, max_age_minutes=30, now=now) is False


def test_daily_bar_stale_check_rejects_older_than_allowed_day_gap() -> None:
    scoring = _load_module("qgpi_scoring_old_stale", "scoring.py")
    now = scoring.datetime(2026, 3, 9, 9, 30, tzinfo=scoring.UTC)
    last_updated = now - timedelta(days=5)
    assert scoring.stale_data_detected(last_updated, max_age_minutes=30, now=now) is True


def test_daily_bar_stale_check_allows_long_weekend_gap() -> None:
    scoring = _load_module("qgpi_scoring_long_weekend", "scoring.py")
    now = scoring.datetime(2026, 5, 26, 9, 30, tzinfo=scoring.UTC)
    last_updated = scoring.datetime(2026, 5, 22, 16, 0, tzinfo=scoring.UTC)
    assert scoring.stale_data_detected(last_updated, max_age_minutes=30, now=now) is False


def test_cloud_scoring_uses_sector_relative_thresholds() -> None:
    scoring = _load_module("qgpi_scoring_sector_relative", "scoring.py")
    config = scoring.load_strategy_config(PROJECT_DIR / "config.py")
    config["strategy"]["thresholds"]["roe_min"] = 0.30
    config["strategy"]["thresholds"]["revenue_growth_min"] = 0.30
    config["strategy"]["thresholds"]["net_income_growth_min"] = 0.30
    config["strategy"]["thresholds"]["sector_percentile_min"] = 0.5
    now = scoring.datetime.now(scoring.UTC)

    ranked = scoring.rank_fundamental_candidates(
        [
            scoring.FundamentalSnapshot(
                symbol="AAA",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="10",
                roe=0.14,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.16,
                net_income_growth=0.12,
                pe_ratio=20,
                peg_ratio=0.8,
            ),
            scoring.FundamentalSnapshot(
                symbol="AAB",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="10",
                roe=0.10,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.11,
                net_income_growth=0.08,
                pe_ratio=20,
                peg_ratio=1.1,
            ),
        ],
        config,
    )

    assert [candidate.symbol for candidate in ranked] == ["AAA"]


def test_cloud_scoring_allocates_by_combined_score() -> None:
    scoring = _load_module("qgpi_scoring_weighted_targets", "scoring.py")
    config = scoring.load_strategy_config(PROJECT_DIR / "config.py")
    config["strategy"]["rebalance"]["max_holdings"] = 3
    config["strategy"]["rebalance"]["candidate_pool_multiplier"] = 2
    now = scoring.datetime.now(scoring.UTC)

    intent = scoring.build_rebalance_intent(
        "QualityGrowthPi:2026-03-09",
        [
            scoring.FundamentalSnapshot(
                symbol="AAA",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="10",
                roe=0.30,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.25,
                net_income_growth=0.20,
                pe_ratio=20,
                peg_ratio=0.8,
            ),
            scoring.FundamentalSnapshot(
                symbol="BBB",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="20",
                roe=0.28,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.24,
                net_income_growth=0.19,
                pe_ratio=20,
                peg_ratio=0.9,
            ),
            scoring.FundamentalSnapshot(
                symbol="CCC",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="30",
                roe=0.26,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.23,
                net_income_growth=0.18,
                pe_ratio=20,
                peg_ratio=1.0,
            ),
            scoring.FundamentalSnapshot(
                symbol="DDD",
                as_of=now,
                has_fundamental_data=True,
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                sector_code="40",
                roe=0.24,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.22,
                net_income_growth=0.17,
                pe_ratio=20,
                peg_ratio=1.1,
            ),
        ],
        {
            "AAA": scoring.TimingFeatures(
                symbol="AAA",
                relative_volume=0.0,
                volatility_ratio=1.0,
                short_sma=0.0,
                long_sma=0.0,
                trend_up=False,
                volatility_contraction=False,
                timing_score=0.7,
                last_updated=now,
            ),
            "BBB": scoring.TimingFeatures(
                symbol="BBB",
                relative_volume=0.0,
                volatility_ratio=1.0,
                short_sma=0.0,
                long_sma=0.0,
                trend_up=False,
                volatility_contraction=False,
                timing_score=0.4,
                last_updated=now,
            ),
            "CCC": scoring.TimingFeatures(
                symbol="CCC",
                relative_volume=0.0,
                volatility_ratio=1.0,
                short_sma=0.0,
                long_sma=0.0,
                trend_up=False,
                volatility_contraction=False,
                timing_score=0.3,
                last_updated=now,
            ),
            "DDD": scoring.TimingFeatures(
                symbol="DDD",
                relative_volume=0.0,
                volatility_ratio=1.0,
                short_sma=0.0,
                long_sma=0.0,
                trend_up=False,
                volatility_contraction=False,
                timing_score=0.2,
                last_updated=now,
            ),
        },
        config,
    )

    assert intent.selected_symbols == ["AAA", "BBB", "CCC"]
    assert intent.target_weights["AAA"] > intent.target_weights["BBB"] > intent.target_weights["CCC"]
