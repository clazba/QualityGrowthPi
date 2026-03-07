"""Cached response replay tests."""

from datetime import datetime
from pathlib import Path

from src.models import DeterministicDecisionContext, EventUrgency, LLMMode, NewsEvent, SentimentLabel, SuggestedAction
from src.sentiment.advisory_engine import AdvisoryEngine
from src.sentiment.cache import LLMResponseCache, build_cache_key
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.prompt_builder import build_advisory_prompt, load_prompt_template
from src.sentiment.schemas import load_schema
from src.settings import load_settings
from src.state_store import StateStore


def test_cached_advisory_is_replayed_without_provider(tmp_path: Path) -> None:
    settings = load_settings()
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    schema = load_schema(Path("config/prompts/extraction_schema.json"))
    system_prompt = load_prompt_template(Path("config/prompts/advisory_system.txt"))
    context = DeterministicDecisionContext(
        symbol="AAA",
        fundamental_score=0.9,
        timing_score=0.7,
        combined_score=0.82,
        target_weight=0.05,
    )
    events = [
        NewsEvent(
            event_id="1",
            symbol="AAA",
            headline="Fixture event",
            body="Test body",
            source="fixture",
            published_at=datetime.fromisoformat("2026-03-01T12:00:00+00:00"),
        )
    ]
    prompt, version = build_advisory_prompt(system_prompt, context, events)
    cache_key = build_cache_key("AAA", "fixture-model", version, prompt)
    store.put_llm_cache(
        cache_key=cache_key,
        provider="gemini",
        model_name="fixture-model",
        prompt_version=version,
        response_hash="abc",
        payload={
            "symbol": "AAA",
            "sentiment_score": 0.1,
            "sentiment_label": SentimentLabel.NEUTRAL.value,
            "confidence_score": 0.75,
            "key_catalysts": ["product_cycle"],
            "key_risks": ["valuation"],
            "narrative_tags": ["ai"],
            "event_urgency": EventUrgency.MEDIUM.value,
            "suggested_action": SuggestedAction.CAUTION.value,
            "rationale_short": "Cached advisory payload.",
            "source_coverage_score": 0.7,
            "model_name": "fixture-model",
            "prompt_version": version
        },
        ttl_minutes=10,
    )
    engine = AdvisoryEngine(
        provider=None,
        schema=schema,
        advisory_prompt_path=Path("config/prompts/advisory_system.txt"),
        model_name="fixture-model",
        cache=LLMResponseCache(store),
        feature_store=SentimentFeatureStore(store),
        llm_mode=LLMMode.OBSERVE_ONLY,
        policy=settings.llm.policy,
        cache_ttl_minutes=10,
        daily_budget_usd=settings.llm.budget_usd_daily,
        estimated_request_cost_usd=settings.llm.estimated_request_cost_usd,
    )
    advisory = engine.evaluate(context, events)
    assert advisory is not None
    assert advisory.symbol == "AAA"
    assert advisory.prompt_version == version
