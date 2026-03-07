"""Integration tests for SQLite state handling."""

from pathlib import Path

from src.models import AdvisoryEnvelope, EventUrgency, LLMAdvisoryOutput, RiskDecision, SentimentLabel, SentimentSnapshot, SuggestedAction
from src.state_store import StateStore


def test_state_store_initializes_and_persists_llm_records(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "quant_gpt.db")
    store.initialize()

    store.put_llm_cache(
        cache_key="abc",
        provider="gemini",
        model_name="test-model",
        prompt_version="advisory_v1",
        response_hash="hash",
        payload={"symbol": "AAA", "sentiment_score": 0.0},
        ttl_minutes=10,
    )
    assert store.get_llm_cache("abc") == {"symbol": "AAA", "sentiment_score": 0.0}

    store.save_sentiment_snapshot(
        SentimentSnapshot(
            symbol="AAA",
            sentiment_score=0.1,
            sentiment_label=SentimentLabel.NEUTRAL,
            confidence_score=0.8,
            source_coverage_score=0.7,
            key_catalysts=["product_cycle"],
            key_risks=["valuation"],
        )
    )
    store.save_advisory_envelope(
        AdvisoryEnvelope(
            advisory=LLMAdvisoryOutput(
                symbol="AAA",
                sentiment_score=0.1,
                sentiment_label=SentimentLabel.NEUTRAL,
                confidence_score=0.8,
                key_catalysts=["product_cycle"],
                key_risks=["valuation"],
                narrative_tags=["tech"],
                event_urgency=EventUrgency.MEDIUM,
                suggested_action=SuggestedAction.CAUTION,
                rationale_short="Mixed news flow.",
                source_coverage_score=0.7,
                model_name="test-model",
                prompt_version="advisory_v1",
            ),
            decision=RiskDecision(
                symbol="AAA",
                base_weight=0.05,
                adjusted_weight=0.05,
                reason="No effect applied",
            ),
        ),
        policy_mode="observe_only",
    )
    assert len(store.latest_advisories(limit=5)) == 1
