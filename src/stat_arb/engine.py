"""Top-level orchestration for the graph-clustered stat-arb strategy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.models import ClusterSnapshot, MLTradeFilterDecision, PairCandidate, PairPositionState, PairTradeIntent, StatArbSettings
from src.provider_adapters.base import MarketDataProvider, ProviderError
from src.stat_arb.graph import build_clusters, cluster_summary
from src.stat_arb.ml_filter import build_trade_filter
from src.stat_arb.risk import build_pair_trade_intents, evaluate_pair_exit
from src.stat_arb.signals import build_pair_candidates


@dataclass(frozen=True)
class StatArbCycle:
    """Deterministic output of one stat-arb research/evaluation cycle."""

    as_of: datetime
    clusters: list[ClusterSnapshot]
    candidates: list[PairCandidate]
    decisions: dict[str, MLTradeFilterDecision]
    intents: list[PairTradeIntent]
    exits: list[dict[str, object]]
    skipped_symbols: list[str]
    ml_filter_status: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        accepted = [decision for decision in self.decisions.values() if decision.execute]
        rejected = [decision for decision in self.decisions.values() if not decision.execute]
        return {
            "as_of": self.as_of.isoformat(),
            "clusters": cluster_summary(self.clusters),
            "candidate_count": len(self.candidates),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "intent_count": len(self.intents),
            "exit_count": len([exit_signal for exit_signal in self.exits if bool(exit_signal["should_exit"])]),
            "skipped_symbols": list(self.skipped_symbols),
            "ml_filter_status": dict(self.ml_filter_status),
        }


def collect_price_history(
    provider: MarketDataProvider,
    settings: StatArbSettings,
) -> tuple[dict[str, list[float]], list[str]]:
    """Fetch daily close history for the configured stat-arb universe."""

    price_history: dict[str, list[float]] = {}
    skipped_symbols: list[str] = []
    for symbol in settings.universe.symbols:
        try:
            bars = provider.fetch_daily_bars(symbol, settings.universe.lookback_days)
        except ProviderError:
            skipped_symbols.append(symbol)
            continue
        closes = [float(value) for value in bars.get("closes", []) if value is not None]
        if len(closes) < settings.universe.min_history_days:
            skipped_symbols.append(symbol)
            continue
        if closes[-1] < settings.universe.min_price:
            skipped_symbols.append(symbol)
            continue
        price_history[symbol] = closes
    return price_history, skipped_symbols


def run_stat_arb_cycle(
    settings: StatArbSettings,
    price_history: dict[str, list[float]],
    *,
    as_of: datetime | None = None,
    portfolio_equity: float = 100_000.0,
    open_positions: Iterable[PairPositionState] | None = None,
) -> StatArbCycle:
    """Run the full research -> signal -> ML filter -> sizing cycle."""

    cycle_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    open_positions_list = list(open_positions or [])
    clusters = build_clusters(cycle_as_of, price_history, settings)
    candidates = build_pair_candidates(clusters, price_history, settings, cycle_as_of)
    trade_filter = build_trade_filter(settings)
    decisions = {candidate.pair_id: trade_filter.score(candidate) for candidate in candidates}
    filter_status = trade_filter.status_snapshot()
    decision_fallbacks = [decision.metadata for decision in decisions.values() if decision.metadata.get("fallback_active")]
    if decision_fallbacks:
        latest = decision_fallbacks[0]
        filter_status["active_mode"] = latest.get("active_mode", filter_status.get("active_mode"))
        filter_status["fallback_active"] = True
        filter_status["load_status"] = latest.get("load_status", filter_status.get("load_status"))
        if latest.get("last_error"):
            filter_status["last_error"] = latest["last_error"]
    intents = build_pair_trade_intents(candidates, decisions, settings, portfolio_equity, open_positions_list)

    candidate_map = {candidate.pair_id: candidate for candidate in candidates}
    exits = [
        evaluate_pair_exit(position, candidate_map.get(position.pair_id), settings, cycle_as_of)
        for position in open_positions_list
        if position.status == "open"
    ]

    return StatArbCycle(
        as_of=cycle_as_of,
        clusters=clusters,
        candidates=candidates,
        decisions=decisions,
        intents=intents,
        exits=exits,
        skipped_symbols=[],
        ml_filter_status=filter_status,
    )
