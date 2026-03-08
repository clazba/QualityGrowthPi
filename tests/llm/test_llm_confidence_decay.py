"""LLM confidence decay regression checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models import DeterministicDecisionContext, EventUrgency, LLMMode, NewsEvent, SentimentLabel, SuggestedAction
from src.provider_adapters.base import LLMProvider
from src.sentiment.advisory_engine import AdvisoryEngine
from src.sentiment.cache import LLMResponseCache
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.schemas import load_schema
from src.settings import load_settings
from src.state_store import StateStore


class _FixtureProvider(LLMProvider):
    def provider_name(self) -> str:
        return "fixture_llm"

    def generate_json(self, prompt: str, system_prompt: str, schema: dict, model_name: str) -> dict:
        return {
            "symbol": "AAA",
            "sentiment_score": -0.5,
            "sentiment_label": SentimentLabel.BEARISH.value,
            "confidence_score": 0.9,
            "key_catalysts": [],
            "key_risks": ["demand"],
            "narrative_tags": ["earnings"],
            "event_urgency": EventUrgency.HIGH.value,
            "suggested_action": SuggestedAction.REDUCE_SIZE.value,
            "rationale_short": "Fixture advisory for decay testing.",
            "source_coverage_score": 0.9,
            "model_name": model_name,
            "prompt_version": "advisory_v1",
        }


def _engine(tmp_path: Path, half_life_hours: float = 24.0) -> AdvisoryEngine:
    settings = load_settings()
    policy = settings.llm.policy.model_copy(update={"confidence_half_life_hours": half_life_hours})
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    return AdvisoryEngine(
        provider=_FixtureProvider(),
        schema=load_schema(Path("config/prompts/extraction_schema.json")),
        advisory_prompt_path=Path("config/prompts/advisory_system.txt"),
        model_name="fixture-model",
        cache=LLMResponseCache(store),
        feature_store=SentimentFeatureStore(store),
        llm_mode=LLMMode.RISK_MODIFIER,
        policy=policy,
        cache_ttl_minutes=10,
        daily_budget_usd=settings.llm.budget_usd_daily,
        estimated_request_cost_usd=settings.llm.estimated_request_cost_usd,
    )


def _context() -> DeterministicDecisionContext:
    return DeterministicDecisionContext(
        symbol="AAA",
        fundamental_score=0.9,
        timing_score=0.7,
        combined_score=0.82,
        target_weight=0.1,
    )


def test_old_news_decay_forces_no_effect(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    event = NewsEvent(
        event_id="1",
        symbol="AAA",
        headline="Fixture event",
        body="Stale body",
        source="fixture",
        published_at=datetime.now(UTC) - timedelta(days=7),
    )

    envelope = engine.evaluate_with_policy(_context(), [event])

    assert envelope is not None
    assert envelope.decision.action_taken == SuggestedAction.NO_EFFECT
    assert envelope.decision.effective_confidence_score is not None
    assert envelope.decision.effective_confidence_score < 0.1
    assert envelope.decision.decay_factor is not None
    assert envelope.decision.decay_factor < 0.01


def test_fresh_news_preserves_reduce_size_signal(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    event = NewsEvent(
        event_id="1",
        symbol="AAA",
        headline="Fixture event",
        body="Fresh body",
        source="fixture",
        published_at=datetime.now(UTC) - timedelta(hours=1),
    )

    envelope = engine.evaluate_with_policy(_context(), [event])

    assert envelope is not None
    assert envelope.decision.action_taken == SuggestedAction.REDUCE_SIZE
    assert envelope.decision.applied is True
    assert envelope.decision.effective_confidence_score is not None
    assert envelope.decision.effective_confidence_score > 0.5
