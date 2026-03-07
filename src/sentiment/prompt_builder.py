"""Prompt template loading and bounded prompt construction."""

from __future__ import annotations

import json
from pathlib import Path

from src.models import DeterministicDecisionContext, NewsEvent
from src.settings import resolve_project_path


def load_prompt_template(path: Path) -> str:
    """Load a local prompt template."""

    return resolve_project_path(path).read_text(encoding="utf-8").strip()


def extract_prompt_version(prompt_text: str) -> str:
    """Return the version declared on the first line."""

    first_line = prompt_text.splitlines()[0].strip()
    return first_line.replace("version:", "", 1).strip() if first_line.startswith("version:") else "unknown"


def _bounded_news_payload(events: list[NewsEvent], max_items: int = 6, max_body_chars: int = 500) -> list[dict[str, str]]:
    bounded = []
    for event in events[:max_items]:
        bounded.append(
            {
                "headline": event.headline,
                "body": event.body[:max_body_chars],
                "source": event.source,
                "published_at": event.published_at.isoformat(),
            }
        )
    return bounded


def build_advisory_prompt(
    system_prompt: str,
    context: DeterministicDecisionContext,
    events: list[NewsEvent],
) -> tuple[str, str]:
    """Build the user prompt and return it with the resolved prompt version."""

    version = extract_prompt_version(system_prompt)
    user_prompt = json.dumps(
        {
            "deterministic_context": context.model_dump(mode="json"),
            "news_events": _bounded_news_payload(events),
            "instruction": (
                "Return JSON only using the required schema. If evidence is sparse or weak, "
                "prefer suggested_action=no_effect and low confidence."
            ),
        },
        sort_keys=True,
    )
    return user_prompt, version


def build_sentiment_prompt(system_prompt: str, symbol: str, events: list[NewsEvent]) -> tuple[str, str]:
    """Build a sentiment-specific prompt payload."""

    version = extract_prompt_version(system_prompt)
    user_prompt = json.dumps(
        {
            "symbol": symbol,
            "news_events": _bounded_news_payload(events),
            "instruction": "Return JSON only and mark uncertainty explicitly.",
        },
        sort_keys=True,
    )
    return user_prompt, version
