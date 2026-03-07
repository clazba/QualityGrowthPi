"""Curated news ingestion helpers."""

from __future__ import annotations

from datetime import datetime

from src.models import NewsEvent
from src.provider_adapters.factory import build_news_provider
from src.settings import load_settings


def load_curated_news(symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
    """Load news events for a set of symbols using the configured provider stack."""

    provider = build_news_provider(load_settings())
    return provider.fetch_news(symbols=symbols, since=since)
