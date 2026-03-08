"""Graph construction and clustering for the stat-arb strategy."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

import numpy as np

from src.models import ClusterSnapshot, StatArbSettings


def _returns_from_closes(closes: list[float], lookback_days: int) -> np.ndarray:
    trimmed = np.asarray(closes[-(lookback_days + 1) :], dtype=float)
    if trimmed.size < 3:
        return np.asarray([], dtype=float)
    log_prices = np.log(trimmed)
    return np.diff(log_prices)


def build_return_graph(
    price_history: dict[str, list[float]],
    settings: StatArbSettings,
) -> tuple[dict[tuple[str, str], float], dict[str, dict[str, float]]]:
    """Return pairwise correlations and adjacency weights for the configured universe."""

    lookback_days = settings.graph.correlation_lookback_days
    symbols = sorted(price_history)
    correlations: dict[tuple[str, str], float] = {}
    adjacency: dict[str, dict[str, float]] = defaultdict(dict)

    returns_by_symbol = {
        symbol: _returns_from_closes(price_history[symbol], lookback_days)
        for symbol in symbols
    }
    for left, right in combinations(symbols, 2):
        left_returns = returns_by_symbol[left]
        right_returns = returns_by_symbol[right]
        common_length = min(left_returns.size, right_returns.size)
        if common_length < 5:
            continue
        correlation = float(np.corrcoef(left_returns[-common_length:], right_returns[-common_length:])[0, 1])
        if np.isnan(correlation):
            continue
        correlations[(left, right)] = correlation
        if correlation >= settings.graph.min_correlation:
            adjacency[left][right] = correlation
            adjacency[right][left] = correlation
    return correlations, adjacency


def _connected_components(adjacency: dict[str, dict[str, float]]) -> list[list[str]]:
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [start]
        component: list[str] = []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            stack.extend(sorted(adjacency.get(node, {}), reverse=True))
        if component:
            components.append(sorted(component))
    return components


def build_clusters(
    as_of: datetime,
    price_history: dict[str, list[float]],
    settings: StatArbSettings,
) -> list[ClusterSnapshot]:
    """Build deterministic connected-component clusters from the correlation graph."""

    correlations, adjacency = build_return_graph(price_history, settings)
    components = _connected_components(adjacency)
    snapshots: list[ClusterSnapshot] = []
    cluster_index = 1

    for component in components:
        if len(component) < settings.graph.min_cluster_size:
            continue
        bounded_components = [
            component[index : index + settings.graph.max_cluster_size]
            for index in range(0, len(component), settings.graph.max_cluster_size)
        ]
        for symbols in bounded_components:
            if len(symbols) < settings.graph.min_cluster_size:
                continue
            edges = [
                correlations.get((left, right), correlations.get((right, left), 0.0))
                for left, right in combinations(symbols, 2)
                if correlations.get((left, right), correlations.get((right, left), 0.0)) >= settings.graph.min_correlation
            ]
            if not edges:
                continue
            snapshots.append(
                ClusterSnapshot(
                    cluster_id=f"cluster_{cluster_index:03d}",
                    as_of=as_of.astimezone(UTC),
                    symbols=symbols,
                    average_correlation=round(float(np.mean(np.asarray(edges, dtype=float))), 6),
                    edge_count=len(edges),
                    metadata={
                        "correlation_threshold": settings.graph.min_correlation,
                        "correlation_lookback_days": settings.graph.correlation_lookback_days,
                    },
                )
            )
            cluster_index += 1
    return snapshots


def cluster_summary(snapshots: list[ClusterSnapshot]) -> dict[str, Any]:
    """Return a compact report for operator workflows and diagnostics."""

    return {
        "cluster_count": len(snapshots),
        "largest_cluster": max((len(snapshot.symbols) for snapshot in snapshots), default=0),
        "cluster_ids": [snapshot.cluster_id for snapshot in snapshots],
        "symbols": {snapshot.cluster_id: list(snapshot.symbols) for snapshot in snapshots},
    }
