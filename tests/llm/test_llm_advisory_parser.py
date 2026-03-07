"""Advisory parsing tests."""

from pathlib import Path

from src.sentiment.schemas import load_schema, try_validate_payload


def test_advisory_parser_rejects_unknown_fields() -> None:
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
        "prompt_version": "advisory_v1",
        "unexpected": True
    }
    parsed, error = try_validate_payload(payload, schema)
    assert parsed is None
    assert error is not None
