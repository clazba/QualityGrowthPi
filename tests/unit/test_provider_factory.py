"""Unit tests for provider-plan resolution and composite provider builders."""

from pathlib import Path

from src.provider_adapters import build_execution_provider, build_market_data_provider, build_news_provider, resolve_provider_plan
from src.provider_adapters.alpha_vantage_adapter import AlphaVantageNewsProvider
from src.provider_adapters.composite import CompositeMarketDataProvider, CompositeNewsProvider
from src.provider_adapters.alpaca_adapter import AlpacaExecutionAdapter
from src.settings import load_settings


def test_resolve_provider_plan_reflects_default_repo_strategy() -> None:
    settings = load_settings()
    plan = resolve_provider_plan(settings)
    assert plan.strategy_mode == "quality_growth"
    assert plan.backtest_mode == "cloud"
    assert plan.paper_broker == "alpaca"
    assert plan.paper_deployment_target == "cloud"
    assert plan.local_fundamentals_provider == "massive_sec_alpha_vantage"


def test_factory_builds_expected_default_adapters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QUANT_GPT_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_GPT_PROVIDER_MODE", "external_equivalent")
    monkeypatch.setenv("NEWS_PROVIDER_MODE", "composite")
    settings = load_settings()

    execution_provider = build_execution_provider(settings)
    market_data_provider = build_market_data_provider(settings)
    news_provider = build_news_provider(settings)

    assert isinstance(execution_provider, AlpacaExecutionAdapter)
    assert isinstance(market_data_provider, CompositeMarketDataProvider)
    assert isinstance(news_provider, CompositeNewsProvider)
    assert any(isinstance(provider, AlphaVantageNewsProvider) for provider in news_provider.providers)
