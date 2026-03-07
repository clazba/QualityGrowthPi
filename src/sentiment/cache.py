"""Prompt and response cache helpers backed by the SQLite state store."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.state_store import StateStore


def build_cache_key(symbol: str, model_name: str, prompt_version: str, prompt_payload: str) -> str:
    """Build a stable advisory cache key."""

    raw = json.dumps(
        {
            "symbol": symbol,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "prompt_payload": prompt_payload,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMResponseCache:
    """Thin wrapper around the state store cache table."""

    def __init__(self, store: StateStore) -> None:
        self.store = store

    def get(self, cache_key: str) -> dict[str, Any] | None:
        return self.store.get_llm_cache(cache_key)

    def put(
        self,
        cache_key: str,
        provider: str,
        model_name: str,
        prompt_version: str,
        response_hash: str,
        payload: dict[str, Any],
        ttl_minutes: int,
    ) -> None:
        self.store.put_llm_cache(
            cache_key=cache_key,
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            response_hash=response_hash,
            payload=payload,
            ttl_minutes=ttl_minutes,
        )
