"""File-backed news provider for offline and cached advisory workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.models import NewsEvent
from src.provider_adapters.base import NewsProvider, ProviderError


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
