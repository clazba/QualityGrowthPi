"""Operator workflow helper tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import EventUrgency, NewsEvent, SentimentLabel, SuggestedAction
from src.operator_workflow import (
    build_candidate_contexts,
    build_pair_trade_contexts,
    build_workflow_report,
    run_operator_advisories,
)
from src.provider_adapters.base import LLMProvider, NewsProvider
from src.settings import load_settings
from src.state_store import StateStore


class _FixtureNewsProvider(NewsProvider):
    def provider_name(self) -> str:
        return "fixture_news"

    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        return [
            NewsEvent(
                event_id=f"{symbol}-1",
                symbol=symbol,
                headline=f"{symbol} fixture headline",
                body="Fixture event body",
                source="fixture",
                published_at=datetime.fromisoformat("2026-03-01T12:00:00+00:00"),
            )
            for symbol in symbols
        ]


class _FixtureLLMProvider(LLMProvider):
    def provider_name(self) -> str:
        return "fixture_llm"

    def generate_json(self, prompt: str, system_prompt: str, schema: dict, model_name: str) -> dict:
        return {
            "symbol": "AAPL" if "AAPL" in prompt else "MSFT",
            "sentiment_score": 0.2,
            "sentiment_label": SentimentLabel.NEUTRAL.value,
            "confidence_score": 0.72,
            "key_catalysts": ["demand"],
            "key_risks": ["valuation"],
            "narrative_tags": ["ai"],
            "event_urgency": EventUrgency.MEDIUM.value,
            "suggested_action": SuggestedAction.CAUTION.value,
            "rationale_short": "Fixture advisory.",
            "source_coverage_score": 0.65,
            "model_name": model_name,
            "prompt_version": "advisory_v1",
        }


def test_build_candidate_contexts_uses_account_equity() -> None:
    payload = {
        "available": True,
        "account": {"equity": "100000"},
        "positions": [
            {"symbol": "MSFT", "market_value": "12000", "qty": "10", "side": "long", "unrealized_plpc": "0.1"},
            {"symbol": "AAPL", "market_value": "25000", "qty": "25", "side": "long", "unrealized_plpc": "0.2"},
        ],
    }

    contexts = build_candidate_contexts(payload, max_symbols=5)

    assert [context.symbol for context in contexts] == ["AAPL", "MSFT"]
    assert contexts[0].target_weight == 0.25
    assert contexts[1].target_weight == 0.12
    assert "Context derived from current Alpaca paper holdings." in contexts[0].notes[0]


def test_run_operator_advisories_saves_results(monkeypatch, tmp_path: Path) -> None:
    settings = load_settings()
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    contexts = build_candidate_contexts(
        {
            "available": True,
            "account": {"equity": "100000"},
            "positions": [
                {"symbol": "AAPL", "market_value": "18000", "qty": "15", "side": "long", "unrealized_plpc": "0.05"},
            ],
        },
        max_symbols=5,
    )

    monkeypatch.setattr("src.operator_workflow._build_operator_news_provider", lambda settings: _FixtureNewsProvider())
    monkeypatch.setattr("src.operator_workflow._build_llm_provider", lambda settings: _FixtureLLMProvider())

    result = run_operator_advisories(settings=settings, store=store, contexts=contexts)

    assert result["status"] == "ok"
    assert result["evaluated_symbols"] == ["AAPL"]
    latest = store.latest_advisories(limit=5)
    assert latest
    assert latest[0]["symbol"] == "AAPL"


def test_build_workflow_report_includes_llm_section() -> None:
    diagnostics = {
        "summary": {
            "backtest_id": "abc123",
            "name": "Fixture Backtest",
            "backtest_url": "https://example.com/backtest",
            "status": "Completed.",
            "reported_total_orders": 10,
            "closed_trade_count": 4,
            "runtime_statistics": {
                "Return": "12.3 %",
                "LastTimingFeatureCount": "18",
                "LastSuccessfulTargetCount": "12",
                "LastRebalanceCheckState": "already_completed",
                "LastSuccessfulRebalanceKey": "QualityGrowthPi:2026-03",
                "LastUniverseRankedCount": "15",
                "LastUniverseFineCount": "1000",
            },
            "statistics": {"End Equity": "112300"},
        }
    }
    config = {
        "strategy": {
            "thresholds": {
                "roe_min": 0.15,
                "gross_margin_min": 0.3,
                "debt_to_equity_min": 0.0,
                "debt_to_equity_max": 2.0,
                "revenue_growth_min": 0.1,
                "net_income_growth_min": 0.1,
                "peg_ratio_min": 0.0,
                "peg_ratio_max": 2.0,
            },
            "weights": {
                "roe": 0.3,
                "revenue_growth": 0.3,
                "net_income_growth": 0.2,
                "inverse_peg": 0.2,
            },
            "timing": {
                "volume_window": 20,
                "price_window": 20,
                "short_sma": 10,
                "long_sma": 30,
                "relative_volume_threshold": 1.2,
                "volatility_contraction_threshold": 0.85,
            },
            "rebalance": {"max_holdings": 20, "candidate_pool_multiplier": 3},
            "universe": {
                "exchange_id": "NYS",
                "min_market_cap": 1000000000,
                "min_price": 5.0,
                "require_fundamental_data": True,
            },
        }
    }
    positions_payload = {
        "available": True,
        "positions": [
            {"symbol": "AAPL", "qty": "15", "market_value": "18000", "side": "long"},
        ],
    }
    llm_summary = {
        "enabled": True,
        "mode": "observe_only",
        "provider": "gemini",
        "status": "ok",
        "evaluated_symbols": ["AAPL"],
        "news_event_count": 2,
        "saved_advisories": [
            {
                "symbol": "AAPL",
                "suggested_action": "caution",
                "sentiment_label": "neutral",
                "confidence_score": 0.72,
                "source_coverage_score": 0.65,
                "manual_review_required": False,
            }
        ],
    }

    report = build_workflow_report(
        diagnostics=diagnostics,
        config=config,
        paper_status_text="Live status: Running",
        positions_payload=positions_payload,
        llm_summary=llm_summary,
    )

    assert "## 7. LLM Advisory Review" in report
    assert "`AAPL` action=caution sentiment=neutral confidence=0.72 coverage=0.65 manual_review=false" in report


def test_build_pair_trade_contexts_uses_pair_intents() -> None:
    contexts = build_pair_trade_contexts(
        {
            "accepted_intents": [
                {
                    "pair_id": "cluster_001:AAPL:MSFT",
                    "long_symbol": "AAPL",
                    "short_symbol": "MSFT",
                    "long_weight": 0.04,
                    "short_weight": -0.04,
                    "expected_edge_bps": 35.0,
                }
            ]
        }
    )

    assert [context.symbol for context in contexts] == ["AAPL", "MSFT"]
    assert contexts[0].target_weight == 0.04


def test_build_workflow_report_renders_stat_arb_sections() -> None:
    diagnostics = {
        "summary": {
            "backtest_id": "pair123",
            "name": "Fixture Stat Arb",
            "backtest_url": "https://example.com/stat-arb",
            "status": "Completed.",
            "reported_total_orders": 18,
            "closed_trade_count": 7,
            "runtime_statistics": {
                "Return": "8.4 %",
            },
            "statistics": {"End Equity": "108400"},
        }
    }
    config = {
        "strategy": {
            "benchmark_symbol": "SPY",
            "universe": {
                "symbols": ["AAPL", "MSFT", "NVDA", "AVGO"],
                "lookback_days": 90,
                "min_history_days": 60,
                "min_price": 10.0,
            },
            "graph": {
                "correlation_lookback_days": 60,
                "min_correlation": 0.75,
                "min_cluster_size": 2,
                "max_cluster_size": 5,
            },
            "spread": {
                "entry_z_score": 1.75,
                "take_profit_z_score": 0.5,
                "stop_loss_z_score": 3.0,
                "max_half_life_days": 20.0,
                "min_expected_edge_bps": 15.0,
            },
            "exit_policy": {
                "initial_take_profit_z_score": 0.75,
                "minimum_take_profit_z_score": 0.25,
                "initial_stop_loss_z_score": 3.2,
                "minimum_stop_loss_z_score": 1.75,
                "decay_half_life_days": 8.0,
                "max_holding_days": 20,
            },
            "sizing": {
                "max_open_pairs": 6,
                "max_gross_exposure_per_trade": 0.12,
                "max_gross_exposure_total": 0.6,
                "max_net_exposure_total": 0.05,
            },
            "ml_filter": {
                "mode": "object_store_model",
                "model_version": "softvote_v2026_03_08",
                "probability_threshold": 0.58,
                "min_confidence": 0.55,
                "object_store_model_key": "28761844/stat-arb/models/softvote_v2026_03_08/ensemble.joblib",
                "local_model_path": "/tmp/ensemble.joblib",
                "feature_schema_version": "stat_arb_v1",
            },
        }
    }
    positions_payload = {"available": False, "reason": "paper not running"}
    llm_summary = {
        "enabled": True,
        "mode": "observe_only",
        "provider": "gemini",
        "status": "ok",
        "evaluated_symbols": ["AAPL", "MSFT"],
        "news_event_count": 4,
        "saved_advisories": [],
    }
    stat_arb_summary = {
        "summary": {"candidate_count": 3, "accepted_count": 1, "rejected_count": 2, "clusters": {"cluster_count": 1}},
        "ml_filter_status": {
            "configured_mode": "object_store_model",
            "active_mode": "object_store_model",
            "configured_model_key": "28761844/stat-arb/models/softvote_v2026_03_08/ensemble.joblib",
            "loaded_model_version": "softvote_v2026_03_08",
            "feature_schema_version": "stat_arb_v1",
            "fallback_active": False,
            "load_status": "loaded",
        },
        "clusters": [
            {
                "cluster_id": "cluster_001",
                "symbols": ["AAPL", "MSFT", "NVDA"],
                "average_correlation": 0.83,
                "edge_count": 3,
            }
        ],
        "accepted_intents": [
            {
                "pair_id": "cluster_001:AAPL:MSFT",
                "long_symbol": "AAPL",
                "short_symbol": "MSFT",
                "entry_z_score": -2.1,
                "kelly_fraction": 0.06,
                "gross_exposure": 0.08,
                "expected_edge_bps": 28.0,
            }
        ],
        "rejected_pairs": [
            {
                "pair_id": "cluster_001:MSFT:NVDA",
                "z_score": 1.8,
                "expected_edge_bps": 11.0,
                "decision": {
                    "predicted_win_probability": 0.51,
                    "confidence_score": 0.42,
                },
            }
        ],
        "exit_signals": [
            {
                "pair_id": "cluster_001:AAPL:MSFT",
                "reason": "take_profit",
                "current_z_score": 0.4,
                "take_profit_z_score": 0.45,
                "stop_loss_z_score": 2.4,
            }
        ],
        "skipped_symbols": ["AVGO"],
    }

    report = build_workflow_report(
        diagnostics=diagnostics,
        config=config,
        paper_status_text="No live deployment found.",
        positions_payload=positions_payload,
        llm_summary=llm_summary,
        stat_arb_summary=stat_arb_summary,
    )

    assert "## 2. Graph Clusters" in report
    assert "## 4. ML Filter And Kelly Sizing" in report
    assert "configured mode: `object_store_model`" in report
    assert "`cluster_001:AAPL:MSFT` long=`AAPL` short=`MSFT`" in report
    assert "`cluster_001:AAPL:MSFT` reason=take_profit" in report
