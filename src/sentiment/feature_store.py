"""Persistence helpers for sentiment and advisory outputs."""

from __future__ import annotations

from src.models import AdvisoryEnvelope, SentimentSnapshot
from src.state_store import StateStore


class SentimentFeatureStore:
    """Persist sentiment and advisory outputs into the shared state store."""

    def __init__(self, store: StateStore) -> None:
        self.store = store

    def save_sentiment(self, snapshot: SentimentSnapshot) -> None:
        self.store.save_sentiment_snapshot(snapshot)

    def save_advisory(self, envelope: AdvisoryEnvelope, policy_mode: str) -> None:
        self.store.save_advisory_envelope(envelope, policy_mode=policy_mode)
