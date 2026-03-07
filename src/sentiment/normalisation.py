"""Normalize and bound text inputs before prompt construction."""

from __future__ import annotations

import hashlib

from src.models import NewsEvent


def deduplicate_events(events: list[NewsEvent]) -> list[NewsEvent]:
    """Drop duplicate events by hashing core text content."""

    seen: set[str] = set()
    result: list[NewsEvent] = []
    for event in events:
        digest = hashlib.sha256(
            f"{event.symbol}|{event.headline}|{event.body}|{event.published_at.isoformat()}".encode("utf-8")
        ).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        result.append(event)
    return result


def truncate_events(events: list[NewsEvent], max_body_chars: int = 500) -> list[NewsEvent]:
    """Truncate oversized event bodies to keep prompt sizes bounded."""

    return [
        NewsEvent(
            **{
                **event.model_dump(mode="python"),
                "body": event.body[:max_body_chars],
            }
        )
        for event in events
    ]
