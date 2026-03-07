"""LLM policy bound checks."""

from src.models import EventUrgency, LLMAdvisoryOutput, LLMMode, SentimentLabel, SuggestedAction
from src.risk_policy import apply_advisory_policy
from src.settings import load_settings


def test_low_confidence_forces_no_effect() -> None:
    settings = load_settings()
    advisory = LLMAdvisoryOutput(
        symbol="AAA",
        sentiment_score=-0.4,
        sentiment_label=SentimentLabel.BEARISH,
        confidence_score=0.2,
        key_catalysts=[],
        key_risks=["guidance_cut"],
        narrative_tags=["earnings"],
        event_urgency=EventUrgency.HIGH,
        suggested_action=SuggestedAction.REDUCE_SIZE,
        rationale_short="Weak evidence should not alter deterministic sizing.",
        source_coverage_score=0.9,
        model_name="fixture-model",
        prompt_version="advisory_v1",
    )
    decision = apply_advisory_policy(0.05, advisory, LLMMode.RISK_MODIFIER, settings.llm.policy)
    assert decision.adjusted_weight == 0.05
    assert decision.action_taken == SuggestedAction.NO_EFFECT
