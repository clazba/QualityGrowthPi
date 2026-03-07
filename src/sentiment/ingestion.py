"""Curated news ingestion helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from src.models import NewsEvent
from src.provider_adapters.news_base import FileNewsProvider


def load_curated_news(symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
    """Load news events for a set of symbols using the configured file feed."""

    feed_path = Path(
        os.getenv(
            "NEWS_FEED_PATH",
            str(Path.cwd() / "data" / "news_cache" / "news_feed.jsonl"),
        )
    )
    provider = FileNewsProvider(feed_path)
    return provider.fetch_news(symbols=symbols, since=since)
