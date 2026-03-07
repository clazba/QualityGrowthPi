"""Narrative extraction helpers built on the shared advisory schema."""

from __future__ import annotations

from datetime import UTC, datetime

from src.models import EventUrgency, NarrativeSnapshot, NewsEvent


def extract_narrative_snapshot(symbol: str, advisory_output, events: list[NewsEvent]) -> NarrativeSnapshot:
    """Derive a narrative snapshot from an advisory payload and its source events."""

    return NarrativeSnapshot(
        symbol=symbol,
        as_of=datetime.now(UTC),
        narrative_tags=list(advisory_output.narrative_tags if advisory_output else []),
        event_urgency=advisory_output.event_urgency if advisory_output else EventUrgency.UNKNOWN,
    )
