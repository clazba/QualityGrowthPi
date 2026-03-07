"""Schema validation tests for advisory payloads."""

from pathlib import Path

from src.sentiment.schemas import load_schema, validate_payload


def test_advisory_schema_accepts_valid_payload() -> None:
    schema = load_schema(Path("config/prompts/extraction_schema.json"))
    payload = {
        "symbol": "AAA",
        "sentiment_score": 0.3,
        "sentiment_label": "bullish",
        "confidence_score": 0.8,
        "key_catalysts": ["product_cycle"],
        "key_risks": ["valuation"],
        "narrative_tags": ["ai"],
        "event_urgency": "medium",
        "suggested_action": "caution",
        "rationale_short": "Positive demand trend, but valuation remains elevated.",
        "source_coverage_score": 0.7,
        "model_name": "fixture-model",
        "prompt_version": "advisory_v1"
    }
    result = validate_payload(payload, schema)
    assert result.symbol == "AAA"
