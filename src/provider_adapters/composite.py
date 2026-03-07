"""Composite providers used to assemble the local fallback market-data stack."""

from __future__ import annotations

from datetime import datetime

from src.models import FundamentalSnapshot, NewsEvent
from src.provider_adapters.base import MarketDataProvider, NewsProvider, ProviderError


class CompositeMarketDataProvider(MarketDataProvider):
    """Failover market-data provider assembled from specialized adapters."""

    def __init__(
        self,
        fundamentals_providers: list[MarketDataProvider],
        daily_bar_providers: list[MarketDataProvider],
    ) -> None:
        self.fundamentals_providers = fundamentals_providers
        self.daily_bar_providers = daily_bar_providers

    def provider_name(self) -> str:
        fundamentals = ",".join(provider.provider_name() for provider in self.fundamentals_providers)
        daily_bars = ",".join(provider.provider_name() for provider in self.daily_bar_providers)
        return f"composite[{fundamentals}|{daily_bars}]"

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        errors: list[str] = []
        for provider in self.fundamentals_providers:
            try:
                result = provider.fetch_fundamentals(as_of=as_of)
            except ProviderError as exc:
                errors.append(f"{provider.provider_name()}: {exc}")
                continue
            if result:
                return result
        raise ProviderError("No fundamentals provider could satisfy the request. " + " | ".join(errors))

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        errors: list[str] = []
        for provider in self.daily_bar_providers:
            try:
                result = provider.fetch_daily_bars(symbol=symbol, lookback_days=lookback_days)
            except ProviderError as exc:
                errors.append(f"{provider.provider_name()}: {exc}")
                continue
            if result.get("closes") and result.get("volumes"):
                return result
        raise ProviderError(f"No daily-bar provider could satisfy {symbol}. " + " | ".join(errors))


class CompositeNewsProvider(NewsProvider):
    """Merge news from multiple providers while deduplicating on event id."""

    def __init__(self, providers: list[NewsProvider]) -> None:
        self.providers = providers

    def provider_name(self) -> str:
        return "composite"

    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        events_by_id: dict[str, NewsEvent] = {}
        errors: list[str] = []
        for provider in self.providers:
            try:
                provider_events = provider.fetch_news(symbols=symbols, since=since)
            except ProviderError as exc:
                errors.append(f"{provider.provider_name()}: {exc}")
                continue
            for event in provider_events:
                events_by_id.setdefault(event.event_id, event)
        if not events_by_id and errors:
            raise ProviderError("No news provider could satisfy the request. " + " | ".join(errors))
        return sorted(events_by_id.values(), key=lambda item: (item.symbol, item.published_at))
