"""Budget guard tests for advisory requests."""

from datetime import UTC, datetime
from pathlib import Path

from src.models import DeterministicDecisionContext, LLMMode, NewsEvent
from src.provider_adapters.base import LLMProvider
from src.sentiment.advisory_engine import AdvisoryEngine
from src.sentiment.cache import LLMResponseCache
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.schemas import load_schema
from src.settings import load_settings
from src.state_store import StateStore


class DummyProvider(LLMProvider):
    def provider_name(self) -> str:
        return "dummy"

    def generate_json(self, prompt, system_prompt, schema, model_name):  # noqa: ANN001, ANN201
        return {
            "symbol": "AAA",
            "sentiment_score": 0.1,
            "sentiment_label": "neutral",
            "confidence_score": 0.8,
            "key_catalysts": ["product_cycle"],
            "key_risks": ["valuation"],
            "narrative_tags": ["ai"],
            "event_urgency": "medium",
            "suggested_action": "caution",
            "rationale_short": "Dummy provider payload.",
            "source_coverage_score": 0.7,
            "model_name": model_name,
            "prompt_version": "advisory_v1",
        }


def test_budget_guard_blocks_new_requests_when_limit_is_exceeded(tmp_path: Path) -> None:
    settings = load_settings()
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()
    store.record_llm_usage("fixture-model", "AAA", estimated_cost_usd=1.0, cache_hit=False)

    engine = AdvisoryEngine(
        provider=DummyProvider(),
        schema=load_schema(Path("config/prompts/extraction_schema.json")),
        advisory_prompt_path=Path("config/prompts/advisory_system.txt"),
        model_name="fixture-model",
        cache=LLMResponseCache(store),
        feature_store=SentimentFeatureStore(store),
        llm_mode=LLMMode.OBSERVE_ONLY,
        policy=settings.llm.policy,
        cache_ttl_minutes=10,
        daily_budget_usd=1.0,
        estimated_request_cost_usd=0.1,
    )

    advisory = engine.evaluate(
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
                body="Budget guard fixture",
                source="fixture",
                published_at=datetime.now(UTC),
            )
        ],
    )

    assert advisory is None
