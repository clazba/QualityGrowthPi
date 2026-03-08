"""Unit tests for graph clustering and pair generation."""

from __future__ import annotations

from datetime import UTC, datetime

from src.stat_arb.engine import run_stat_arb_cycle
from src.stat_arb.graph import build_clusters
from src.settings import load_settings


def _price_history() -> dict[str, list[float]]:
    return {
        "AAPL": [100, 101, 102, 103, 104, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 105],
        "MSFT": [200, 202, 204, 206, 208, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 210, 208, 206, 204, 202, 200, 198, 196, 198, 200, 202, 204, 206, 208, 210],
        "NVDA": [50, 51, 52, 53, 54, 53, 52, 51, 50, 49, 50, 51, 52, 53, 54, 55, 54, 53, 52, 51, 50, 49, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 56, 55, 54, 53, 52, 51, 50, 49, 50, 51, 52, 53, 54, 55, 56],
        "AVGO": [80, 81, 82, 83, 84, 83, 82, 81, 80, 79, 80, 81, 82, 83, 84, 85, 84, 83, 82, 81, 80, 79, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 86, 85, 84, 83, 82, 81, 80, 79, 80, 81, 82, 83, 84, 85, 86],
    }


def test_build_clusters_groups_highly_correlated_symbols() -> None:
    settings = load_settings()
    clusters = build_clusters(datetime.now(UTC), _price_history(), settings.stat_arb)

    assert clusters
    assert any({"AAPL", "MSFT"}.issubset(set(cluster.symbols)) for cluster in clusters)


def test_run_stat_arb_cycle_produces_candidates_and_decisions() -> None:
    settings = load_settings()
    cycle = run_stat_arb_cycle(settings.stat_arb, _price_history(), portfolio_equity=100_000.0)

    assert cycle.candidates
    assert cycle.decisions
    assert cycle.summary()["candidate_count"] >= 1
