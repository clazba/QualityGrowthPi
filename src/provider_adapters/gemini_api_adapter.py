"""HTTP adapter for Gemini-style structured JSON generation."""

from __future__ import annotations

import json
from typing import Any

import requests

from src.provider_adapters.base import LLMProvider, ProviderError
from src.provider_adapters.gemini_base import GeminiRequest, extract_text_candidate


class GeminiAPIAdapter(LLMProvider):
    """Gemini API adapter with configurable model and endpoint selection."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: int = 12,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "gemini"

    def _build_request(self, prompt: str, system_prompt: str, schema: dict[str, Any], model_name: str) -> GeminiRequest:
        return GeminiRequest(
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=prompt,
            schema=schema,
        )

    def generate_json(
        self,
        prompt: str,
        system_prompt: str,
        schema: dict[str, Any],
        model_name: str,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not configured")

        request_payload = self._build_request(prompt, system_prompt, schema, model_name)
        body = {
            "system_instruction": {
                "parts": [{"text": request_payload.system_prompt}],
            },
            "contents": [
                {
                    "parts": [{"text": request_payload.user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        response = self.session.post(
            f"{self.base_url}/models/{model_name}:generateContent",
            params={"key": self.api_key},
            json=body,
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        raw_text = extract_text_candidate(response.json())
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini returned non-JSON output: {raw_text}") from exc
