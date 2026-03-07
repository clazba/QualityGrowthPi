"""News provider implementations for offline and Massive-backed workflows."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import NewsEvent
from src.provider_adapters.base import NewsProvider, ProviderError
from src.provider_adapters.polygon_adapter import MassiveAdapter


class FileNewsProvider(NewsProvider):
    """Load curated news items from a local JSONL file."""

    def __init__(self, feed_path: Path) -> None:
        self.feed_path = feed_path

    def provider_name(self) -> str:
        return "file"

    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        if not self.feed_path.exists():
            raise ProviderError(f"News feed path does not exist: {self.feed_path}")

        requested = set(symbols)
        events: list[NewsEvent] = []
        with self.feed_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                event = NewsEvent(**payload)
                if event.symbol not in requested:
                    continue
                if since and event.published_at < since:
                    continue
                events.append(event)
        return sorted(events, key=lambda item: (item.symbol, item.published_at))


class MassiveNewsProvider(MassiveAdapter, NewsProvider):
    """Massive v2 reference news provider with pagination and schema-tolerant parsing."""

    DEFAULT_NEWS_PATH_TEMPLATE = "/v2/reference/news"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        news_path_template: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout_seconds=timeout_seconds)
        self.news_path_template = (
            news_path_template
            or os.getenv("MASSIVE_NEWS_PATH_TEMPLATE")
            or self.DEFAULT_NEWS_PATH_TEMPLATE
        )

    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        params: dict[str, Any] = {
            "limit": 1000,
            "sort": "published_utc",
            "order": "desc",
        }
        requested = sorted({symbol.upper() for symbol in symbols if symbol})
        if requested:
            if len(requested) == 1:
                params["ticker"] = requested[0]
            else:
                # Inference from Massive's query-filter extension pattern for multi-ticker news searches.
                params["ticker.any_of"] = ",".join(requested)
        if since is not None:
            params["published_utc.gte"] = since.isoformat()

        raw_results = self._paginate_results(self.news_path_template, params=params)
        events: list[NewsEvent] = []
        for record in raw_results:
            events.extend(self._normalize_news_record(record, requested=requested))
        if since is not None:
            events = [event for event in events if event.published_at >= since]
        return sorted(events, key=lambda item: (item.symbol, item.published_at))

    def _normalize_news_record(self, record: dict[str, Any], requested: list[str]) -> list[NewsEvent]:
        """Normalize a Massive news result into one NewsEvent per requested ticker."""

        article_id = self._first_present(record, ("id",), ("article_id",))
        title = self._first_present(record, ("title",), ("headline",))
        published_at = self._first_present(record, ("published_utc",), ("published_at",))
        article_url = self._first_present(record, ("article_url",), ("url",))
        body = self._first_present(record, ("description",), ("summary",), ("body",)) or ""
        publisher_name = self._first_present(record, ("publisher", "name"), ("source",), ("publisher_name",)) or "massive"
        tickers = self._first_present(record, ("tickers",), ("symbols",)) or []
        if not isinstance(tickers, list):
            tickers = [tickers]

        if article_id is None or title is None or published_at is None:
            return []

        matched_tickers = [str(ticker).upper() for ticker in tickers if str(ticker).upper() in requested] if requested else [str(ticker).upper() for ticker in tickers]
        if not matched_tickers:
            return []

        events: list[NewsEvent] = []
        for ticker in matched_tickers:
            events.append(
                NewsEvent(
                    event_id=f"{article_id}:{ticker}",
                    symbol=ticker,
                    headline=str(title),
                    body=str(body),
                    source=str(publisher_name),
                    published_at=published_at,
                    url=str(article_url) if article_url is not None else None,
                )
            )
        return events
