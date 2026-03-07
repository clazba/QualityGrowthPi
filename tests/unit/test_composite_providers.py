"""Unit tests for composite provider failover and deduplication."""

from datetime import UTC, datetime

from src.models import NewsEvent
from src.provider_adapters.base import MarketDataProvider, NewsProvider, ProviderError
from src.provider_adapters.composite import CompositeMarketDataProvider, CompositeNewsProvider


class _FailingMarketDataProvider(MarketDataProvider):
    def provider_name(self) -> str:
        return "failing"

    def fetch_fundamentals(self, as_of=None):
        raise ProviderError("no fundamentals")

    def fetch_daily_bars(self, symbol: str, lookback_days: int):
        raise ProviderError("no bars")


class _WorkingMarketDataProvider(MarketDataProvider):
    def provider_name(self) -> str:
        return "working"

    def fetch_fundamentals(self, as_of=None):
        return []

    def fetch_daily_bars(self, symbol: str, lookback_days: int):
        return {"closes": [1.0] * lookback_days, "volumes": [100.0] * lookback_days}


class _NewsProvider(NewsProvider):
    def __init__(self, events):
        self.events = events

    def provider_name(self) -> str:
        return "test"

    def fetch_news(self, symbols, since=None):
        return self.events


def test_composite_market_data_provider_falls_back_for_daily_bars() -> None:
    provider = CompositeMarketDataProvider(
        fundamentals_providers=[_FailingMarketDataProvider()],
        daily_bar_providers=[_FailingMarketDataProvider(), _WorkingMarketDataProvider()],
    )
    result = provider.fetch_daily_bars("AAPL", lookback_days=3)
    assert result["closes"] == [1.0, 1.0, 1.0]


def test_composite_news_provider_deduplicates_event_ids() -> None:
    event = NewsEvent(
        event_id="evt-1",
        symbol="AAPL",
        headline="Headline",
        body="Body",
        source="unit",
        published_at=datetime(2026, 3, 7, tzinfo=UTC),
    )
    provider = CompositeNewsProvider([_NewsProvider([event]), _NewsProvider([event])])
    events = provider.fetch_news(["AAPL"])
    assert len(events) == 1
