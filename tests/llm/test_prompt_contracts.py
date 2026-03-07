"""Prompt regression checks to catch accidental drift."""

from pathlib import Path

from src.sentiment.prompt_builder import extract_prompt_version, load_prompt_template


def test_prompt_versions_are_declared() -> None:
    for filename in [
        "sentiment_system.txt",
        "narrative_system.txt",
        "advisory_system.txt",
    ]:
        prompt = load_prompt_template(Path("config/prompts") / filename)
        assert extract_prompt_version(prompt) != "unknown"
        assert "Return JSON only." in prompt
