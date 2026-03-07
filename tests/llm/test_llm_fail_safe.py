"""Fail-open tests for the advisory subsystem."""

from datetime import datetime
from pathlib import Path

from src.models import DeterministicDecisionContext, LLMMode, NewsEvent
from src.sentiment.advisory_engine import AdvisoryEngine
from src.sentiment.cache import LLMResponseCache
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.schemas import load_schema
from src.settings import load_settings
from src.state_store import StateStore


def test_advisory_engine_returns_none_when_provider_is_missing(tmp_path: Path) -> None:
    settings = load_settings()
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    engine = AdvisoryEngine(
        provider=None,
        schema=load_schema(Path("config/prompts/extraction_schema.json")),
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
    result = engine.evaluate(
        DeterministicDecisionContext(
            symbol="AAA",
            fundamental_score=0.9,
            timing_score=0.7,
            combined_score=0.82,
            target_weight=0.05,
        ),
        [
            NewsEvent(
                event_id="1",
                symbol="AAA",
                headline="Fixture event",
                body="Test body",
                source="fixture",
                published_at=datetime.fromisoformat("2026-03-01T12:00:00+00:00"),
            )
        ],
    )
    assert result is None
