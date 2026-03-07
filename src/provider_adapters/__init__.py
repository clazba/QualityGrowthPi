"""Provider adapter exports."""

from src.provider_adapters.alpaca_adapter import AlpacaExecutionAdapter, AlpacaMarketDataAdapter
from src.provider_adapters.alpha_vantage_adapter import AlphaVantageAdapter, AlphaVantageNewsProvider
from src.provider_adapters.base import ExecutionProvider, LLMProvider, MarketDataProvider, NewsProvider
from src.provider_adapters.composite import CompositeMarketDataProvider, CompositeNewsProvider
from src.provider_adapters.factory import build_execution_provider, build_market_data_provider, build_news_provider, resolve_provider_plan
from src.provider_adapters.gemini_api_adapter import GeminiAPIAdapter
from src.provider_adapters.ibkr_adapter import IBKRExecutionAdapter
from src.provider_adapters.news_base import FileNewsProvider, MassiveNewsProvider
from src.provider_adapters.polygon_adapter import MassiveAdapter, PolygonAdapter
from src.provider_adapters.quantconnect_local import QuantConnectLocalAdapter
from src.provider_adapters.sec_adapter import SECFundamentalsAdapter

__all__ = [
    "AlpacaExecutionAdapter",
    "AlpacaMarketDataAdapter",
    "AlphaVantageAdapter",
    "AlphaVantageNewsProvider",
    "build_execution_provider",
    "build_market_data_provider",
    "build_news_provider",
    "CompositeMarketDataProvider",
    "CompositeNewsProvider",
    "ExecutionProvider",
    "FileNewsProvider",
    "GeminiAPIAdapter",
    "IBKRExecutionAdapter",
    "MassiveNewsProvider",
    "LLMProvider",
    "MassiveAdapter",
    "MarketDataProvider",
    "NewsProvider",
    "PolygonAdapter",
    "QuantConnectLocalAdapter",
    "resolve_provider_plan",
    "SECFundamentalsAdapter",
]
