"""Unit tests for bounded advisory influence."""

from src.models import EventUrgency, LLMAdvisoryOutput, LLMMode, SentimentLabel, SuggestedAction
from src.risk_policy import apply_advisory_policy
from src.settings import load_settings


def test_reduce_size_is_bounded_and_requires_manual_review() -> None:
    settings = load_settings()
    advisory = LLMAdvisoryOutput(
        symbol="AAA",
        sentiment_score=-0.6,
        sentiment_label=SentimentLabel.BEARISH,
        confidence_score=0.8,
        key_catalysts=[],
        key_risks=["earnings_miss"],
        narrative_tags=["earnings"],
        event_urgency=EventUrgency.HIGH,
        suggested_action=SuggestedAction.REDUCE_SIZE,
        rationale_short="Negative earnings surprise with elevated uncertainty.",
        source_coverage_score=0.9,
        model_name="test-model",
        prompt_version="advisory_v1",
    )
    decision = apply_advisory_policy(0.05, advisory, LLMMode.RISK_MODIFIER, settings.llm.policy)
    assert decision.applied is True
    assert decision.adjusted_weight < 0.05
    assert decision.manual_review_required is True
