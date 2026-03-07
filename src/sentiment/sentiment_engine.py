"""Sentiment-specific orchestration for schema-validated LLM output."""

from __future__ import annotations

from datetime import UTC, datetime

from src.logging_utils import get_logger
from src.models import DeterministicDecisionContext, NewsEvent, SentimentLabel, SentimentSnapshot
from src.provider_adapters.base import LLMProvider, ProviderError
from src.sentiment.prompt_builder import build_sentiment_prompt, load_prompt_template
from src.sentiment.schemas import validate_payload


class SentimentEngine:
    """Generate and persist sentiment features from curated text inputs."""

    def __init__(self, provider: LLMProvider | None, schema: dict, sentiment_prompt_path, model_name: str) -> None:
        self.provider = provider
        self.schema = schema
        self.sentiment_prompt_path = sentiment_prompt_path
        self.model_name = model_name
        self.logger = get_logger("quant_gpt.llm")

    def fallback_snapshot(self, symbol: str) -> SentimentSnapshot:
        """Return a neutral, low-confidence snapshot when the provider is unavailable."""

        return SentimentSnapshot(
            symbol=symbol,
            as_of=datetime.now(UTC),
            sentiment_score=0.0,
            sentiment_label=SentimentLabel.UNKNOWN,
            confidence_score=0.0,
            source_coverage_score=0.0,
            key_catalysts=[],
            key_risks=["llm_unavailable"],
        )

    def analyze(self, symbol: str, events: list[NewsEvent], context: DeterministicDecisionContext | None = None) -> SentimentSnapshot:
        """Return a schema-validated sentiment snapshot or a fail-open fallback."""

        if not events or self.provider is None:
            return self.fallback_snapshot(symbol)

        system_prompt = load_prompt_template(self.sentiment_prompt_path)
        prompt, _version = build_sentiment_prompt(system_prompt, symbol, events)

        try:
            payload = self.provider.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
                schema=self.schema,
                model_name=self.model_name,
            )
            advisory = validate_payload(payload, self.schema)
        except (ProviderError, ValueError) as exc:
            self.logger.warning("Sentiment analysis failed for %s: %s", symbol, exc)
            return self.fallback_snapshot(symbol)

        return SentimentSnapshot(
            symbol=advisory.symbol,
            as_of=datetime.now(UTC),
            sentiment_score=advisory.sentiment_score,
            sentiment_label=advisory.sentiment_label,
            confidence_score=advisory.confidence_score,
            source_coverage_score=advisory.source_coverage_score,
            key_catalysts=advisory.key_catalysts,
            key_risks=advisory.key_risks,
        )
