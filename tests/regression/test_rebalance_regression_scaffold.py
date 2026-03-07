"""Regression scaffolding using deterministic local fixtures."""

import json
from pathlib import Path

from src.models import FundamentalSnapshot, TimingFeatures
from src.scoring import build_rebalance_intent
from src.settings import load_settings


FIXTURES = Path("tests/regression/fixtures")


def test_rebalance_fixture_matches_expected_targets() -> None:
    settings = load_settings()
    strategy = settings.strategy.model_copy(
        update={
            "rebalance": settings.strategy.rebalance.model_copy(
                update={"max_holdings": 3, "candidate_pool_multiplier": 2}
            )
        }
    )
    universe_payload = json.loads((FIXTURES / "universe_snapshot.json").read_text(encoding="utf-8"))
    timing_payload = json.loads((FIXTURES / "timing_snapshot.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "expected_targets.json").read_text(encoding="utf-8"))

    snapshots = [FundamentalSnapshot(**row) for row in universe_payload]
    timing_map = {symbol: TimingFeatures(**payload) for symbol, payload in timing_payload.items()}
    intent = build_rebalance_intent(expected["rebalance_key"], snapshots, timing_map, strategy)

    assert intent.selected_symbols == expected["selected_symbols"]
    assert intent.target_weights == expected["target_weights"]
