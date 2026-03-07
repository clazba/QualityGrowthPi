"""Gemini adapter utilities and request shaping."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.provider_adapters.base import ProviderError


@dataclass(frozen=True)
class GeminiRequest:
    """Prepared Gemini request payload."""

    model_name: str
    system_prompt: str
    user_prompt: str
    schema: dict[str, Any]

    @property
    def response_hash_seed(self) -> str:
        payload = {
            "model_name": self.model_name,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "schema": self.schema,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def extract_text_candidate(payload: dict[str, Any]) -> str:
    """Extract the first text candidate from a Gemini JSON response."""

    candidates = payload.get("candidates", [])
    if not candidates:
        raise ProviderError("Gemini response contained no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ProviderError("Gemini response contained no content parts")
    text = parts[0].get("text")
    if not text:
        raise ProviderError("Gemini response did not include a text part")
    return text
