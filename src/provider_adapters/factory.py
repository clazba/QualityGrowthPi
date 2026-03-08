"""Provider-plan resolution and adapter factories."""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from src.provider_adapters.alpaca_adapter import AlpacaExecutionAdapter, AlpacaMarketDataAdapter
from src.provider_adapters.alpha_vantage_adapter import AlphaVantageAdapter, AlphaVantageNewsProvider
from src.provider_adapters.base import ExecutionProvider, MarketDataProvider, NewsProvider
from src.provider_adapters.composite import CompositeMarketDataProvider, CompositeNewsProvider
from src.provider_adapters.ibkr_adapter import IBKRExecutionAdapter
from src.provider_adapters.news_base import FileNewsProvider, MassiveNewsProvider
from src.provider_adapters.polygon_adapter import MassiveAdapter
from src.provider_adapters.quantconnect_local import QuantConnectLocalAdapter
from src.provider_adapters.sec_adapter import SECFundamentalsAdapter
from src.settings import Settings


@dataclass(frozen=True)
class ResolvedProviderPlan:
    """Concrete provider plan resolved from settings and environment."""

    strategy_mode: str
    backtest_mode: str
    backtest_project: str
    paper_deployment_target: str
    paper_broker: str
    paper_environment: str
    paper_live_data_provider: str
    paper_historical_data_provider: str
    local_fundamentals_provider: str
    local_daily_bars_provider: str
    local_news_provider: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_provider_plan(settings: Settings) -> ResolvedProviderPlan:
    """Return the active deployment/provider plan."""

    return ResolvedProviderPlan(
        strategy_mode=settings.runtime.strategy_mode.value,
        backtest_mode=settings.backtest.mode.value,
        backtest_project=settings.backtest.project_name,
        paper_deployment_target=settings.paper_trading.deployment_target.value,
        paper_broker=settings.paper_trading.broker.value,
        paper_environment=settings.paper_trading.environment,
        paper_live_data_provider=settings.paper_trading.live_data_provider,
        paper_historical_data_provider=settings.paper_trading.historical_data_provider,
        local_fundamentals_provider=settings.local_data_stack.fundamentals_provider,
        local_daily_bars_provider=settings.local_data_stack.daily_bars_provider,
        local_news_provider=settings.local_data_stack.news_provider.value,
    )


def build_execution_provider(settings: Settings) -> ExecutionProvider:
    """Return the configured paper/live execution adapter."""

    broker = settings.paper_trading.broker.value
    if broker == "alpaca":
        return AlpacaExecutionAdapter(environment=settings.paper_trading.environment)
    if broker == "ibkr":
        return IBKRExecutionAdapter(
            host=os.getenv("IBKR_HOST", "127.0.0.1"),
            port=int(os.getenv("IBKR_PORT", "7497")),
            account=os.getenv("IBKR_ACCOUNT", ""),
            client_id=int(os.getenv("IBKR_CLIENT_ID", "101")),
        )
    raise ValueError(f"Unsupported paper broker: {broker}")


def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    """Return the active market-data adapter or composite fallback stack."""

    if settings.runtime.provider_mode.value == "quantconnect_local":
        lean_data_directory = Path(os.getenv("LEAN_DATA_DIRECTORY", str(settings.data_dir / "lean")))
        return QuantConnectLocalAdapter(data_directory=lean_data_directory)

    fundamentals_providers: list[MarketDataProvider] = []
    daily_bar_providers: list[MarketDataProvider] = []

    if settings.local_data_stack.fundamentals_provider == "massive_sec_alpha_vantage":
        fundamentals_providers.extend(
            [
                MassiveAdapter(),
                SECFundamentalsAdapter(),
                AlphaVantageAdapter(),
            ]
        )
    elif settings.local_data_stack.fundamentals_provider == "sec":
        fundamentals_providers.append(SECFundamentalsAdapter())
    elif settings.local_data_stack.fundamentals_provider == "alpha_vantage":
        fundamentals_providers.append(AlphaVantageAdapter())
    else:
        fundamentals_providers.append(MassiveAdapter())

    if settings.local_data_stack.daily_bars_provider == "alpaca":
        daily_bar_providers.extend([AlpacaMarketDataAdapter(), MassiveAdapter(), AlphaVantageAdapter()])
    elif settings.local_data_stack.daily_bars_provider == "massive":
        daily_bar_providers.extend([MassiveAdapter(), AlphaVantageAdapter(), AlpacaMarketDataAdapter()])
    else:
        daily_bar_providers.extend([AlphaVantageAdapter(), MassiveAdapter(), AlpacaMarketDataAdapter()])

    return CompositeMarketDataProvider(
        fundamentals_providers=fundamentals_providers,
        daily_bar_providers=daily_bar_providers,
    )


def build_news_provider(settings: Settings) -> NewsProvider:
    """Return the configured news provider."""

    file_provider = FileNewsProvider(
        Path(os.getenv("NEWS_FEED_PATH", str(settings.data_dir / "news_cache" / "news_feed.jsonl")))
    )
    mode = settings.local_data_stack.news_provider.value
    if mode == "file":
        return file_provider
    if mode == "massive":
        return MassiveNewsProvider()
    if mode == "alpha_vantage":
        return AlphaVantageNewsProvider()
    return CompositeNewsProvider([file_provider, AlphaVantageNewsProvider(), MassiveNewsProvider()])
