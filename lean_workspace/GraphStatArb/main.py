"""Cloud-safe LEAN entrypoint for the graph-clustered stat-arb strategy."""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional


PROJECT_DIR = Path(__file__).resolve().parent
UTC = timezone.utc
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    from AlgorithmImports import *  # type: ignore  # noqa: F401,F403
except ImportError:  # pragma: no cover - local syntax support only
    pass

if "QCAlgorithm" not in globals():  # pragma: no cover - local syntax support only
    class QCAlgorithm:
        pass

if "Resolution" not in globals():  # pragma: no cover - local syntax support only
    class Resolution:
        Daily = "Daily"


from stat_arb import PairPositionState, build_trade_filter, load_strategy_config, run_stat_arb_cycle


DAILY_RESOLUTION = getattr(Resolution, "Daily", getattr(Resolution, "DAILY", "Daily"))


class SymbolState:
    """Rolling close-only state for daily stat-arb features."""

    def __init__(self, maxlen: int) -> None:
        self.closes = deque(maxlen=maxlen)  # type: Deque[float]
        self.last_updated = None  # type: Optional[datetime]

    def extend(self, closes: List[float], last_updated: Optional[datetime] = None) -> None:
        for close in closes:
            self.closes.append(float(close))
        if last_updated is not None:
            self.last_updated = last_updated

    def add_bar(self, close: float, last_updated: datetime) -> None:
        self.closes.append(float(close))
        self.last_updated = last_updated


class GraphStatArbAlgorithm(QCAlgorithm):
    """Daily graph-clustered stat-arb algorithm for LEAN cloud deployment."""

    def Initialize(self) -> None:  # noqa: N802
        self.config = load_strategy_config(PROJECT_DIR / "config.py")
        self.strategy = self.config["strategy"]
        self.runtime = self.config.get("runtime", {})
        self.audit_enabled = bool(self.runtime.get("cloud_audit_logging", True))
        self.symbol_registry = {}  # type: Dict[str, Any]
        self.symbol_state = {}  # type: Dict[str, SymbolState]
        self.open_pairs = {}  # type: Dict[str, PairPositionState]
        self.trade_filter = None
        self.trade_filter_status = {}  # type: Dict[str, Any]

        start_date = datetime.strptime(str(self.runtime.get("backtest_start_date", "2022-01-01")), "%Y-%m-%d")
        if hasattr(self, "SetStartDate"):
            self.SetStartDate(start_date.year, start_date.month, start_date.day)
        if hasattr(self, "SetCash"):
            self.SetCash(float(self.runtime.get("initial_cash", 100_000.0)))
        if hasattr(self, "UniverseSettings"):
            self.UniverseSettings.Resolution = DAILY_RESOLUTION

        self.symbols = list(self.strategy["universe"]["symbols"])
        benchmark_ticker = self.strategy.get("benchmark_symbol", "SPY")
        if hasattr(self, "AddEquity"):
            self.benchmark_symbol = self.AddEquity(benchmark_ticker, DAILY_RESOLUTION).Symbol
            for ticker in self.symbols:
                symbol = self.AddEquity(ticker, DAILY_RESOLUTION).Symbol
                self.symbol_registry[ticker] = symbol
                self.symbol_state[ticker] = SymbolState(int(self.strategy["universe"]["lookback_days"]))
        else:
            self.benchmark_symbol = benchmark_ticker
            for ticker in self.symbols:
                self.symbol_registry[ticker] = ticker
                self.symbol_state[ticker] = SymbolState(int(self.strategy["universe"]["lookback_days"]))

        if hasattr(self, "SetBenchmark"):
            self.SetBenchmark(self.benchmark_symbol)

        self._bootstrap_history()
        self.trade_filter, filter_status = build_trade_filter(self.config, object_store=getattr(self, "ObjectStore", None))
        self.trade_filter_status = dict(filter_status.model_dump())

        if hasattr(self, "Schedule") and hasattr(self, "DateRules") and hasattr(self, "TimeRules"):
            anchor = self.symbol_registry.get(self.symbols[0], self.benchmark_symbol)
            self.Schedule.On(
                self.DateRules.EveryDay(anchor),
                self.TimeRules.AfterMarketOpen(anchor, 30),
                self.ScanPairs,
            )
        self._set_runtime_statistic("LastCycleState", "initialized")
        self._set_runtime_statistic("LastClusterCount", "0")
        self._set_runtime_statistic("LastCandidateCount", "0")
        self._set_runtime_statistic("LastAcceptedCount", "0")
        self._set_runtime_statistic("OpenPairCount", "0")
        self._publish_filter_runtime_statistics(self.trade_filter_status)

    def _bootstrap_history(self) -> None:
        history = getattr(self, "History", None)
        if history is None:
            return
        history_days = int(self.runtime.get("bootstrap_history_days", 120))
        for ticker, symbol in self.symbol_registry.items():
            try:
                bars = history(symbol, history_days, DAILY_RESOLUTION)
            except Exception:
                continue
            closes: List[float] = []
            last_updated = None
            if hasattr(bars, "itertuples"):
                for row in bars.itertuples():
                    close = getattr(row, "close", getattr(row, "Close", None))
                    timestamp = getattr(row, "Index", None)
                    if close is None:
                        continue
                    closes.append(float(close))
                    if timestamp is not None:
                        try:
                            last_updated = timestamp.to_pydatetime().astimezone(UTC)
                        except Exception:
                            pass
            else:
                for bar in bars:
                    close = getattr(bar, "Close", None)
                    if close is None:
                        continue
                    closes.append(float(close))
                    end_time = getattr(bar, "EndTime", None)
                    if end_time is not None:
                        last_updated = end_time.astimezone(UTC)
            if closes:
                self.symbol_state[ticker].extend(closes, last_updated=last_updated)

    def OnData(self, data) -> None:  # noqa: N802
        for ticker, symbol in self.symbol_registry.items():
            try:
                bar = data.Bars[symbol]
            except Exception:
                bar = None
            if bar is None:
                continue
            end_time = getattr(bar, "EndTime", None) or datetime.now(UTC)
            if hasattr(end_time, "astimezone"):
                end_time = end_time.astimezone(UTC)
            self.symbol_state[ticker].add_bar(float(bar.Close), end_time)

    def _price_history(self) -> Dict[str, List[float]]:
        history: Dict[str, List[float]] = {}
        min_history_days = int(self.strategy["universe"]["min_history_days"])
        min_price = float(self.strategy["universe"]["min_price"])
        for ticker, state in self.symbol_state.items():
            closes = list(state.closes)
            if len(closes) < min_history_days:
                continue
            if closes[-1] < min_price:
                continue
            history[ticker] = closes
        return history

    def ScanPairs(self) -> None:  # noqa: N802
        price_history = self._price_history()
        if len(price_history) < 2:
            self._set_runtime_statistic("LastCycleState", "insufficient_history")
            return

        portfolio_value = float(getattr(getattr(self, "Portfolio", None), "TotalPortfolioValue", 100_000.0))
        now = self.UtcTime.astimezone(UTC) if hasattr(self, "UtcTime") else datetime.now(UTC)
        cycle = run_stat_arb_cycle(
            self.config,
            price_history,
            now,
            portfolio_value,
            list(self.open_pairs.values()),
            trade_filter=self.trade_filter,
        )
        self.trade_filter_status = dict(cycle.ml_filter_status)
        self._set_runtime_statistic("LastClusterCount", str(len(cycle.clusters)))
        self._set_runtime_statistic("LastCandidateCount", str(len(cycle.candidates)))
        self._set_runtime_statistic(
            "LastAcceptedCount",
            str(len([decision for decision in cycle.decisions.values() if decision.execute])),
        )
        self._publish_filter_runtime_statistics(self.trade_filter_status)

        for exit_signal in cycle.exits:
            if not exit_signal["should_exit"]:
                continue
            pair_id = str(exit_signal["pair_id"])
            state = self.open_pairs.pop(pair_id, None)
            if state is None:
                continue
            liquidate = getattr(self, "Liquidate", None)
            if liquidate is not None:
                liquidate(self.symbol_registry[state.long_symbol], "pair exit")
                liquidate(self.symbol_registry[state.short_symbol], "pair exit")

        candidate_map = {candidate.pair_id: candidate for candidate in cycle.candidates}
        for pair_id, state in list(self.open_pairs.items()):
            candidate = candidate_map.get(pair_id)
            if candidate is None:
                continue
            self.open_pairs[pair_id] = PairPositionState(
                pair_id=state.pair_id,
                cluster_id=state.cluster_id,
                long_symbol=state.long_symbol,
                short_symbol=state.short_symbol,
                opened_at=state.opened_at,
                status=state.status,
                entry_z_score=state.entry_z_score,
                latest_z_score=candidate.spread_features.z_score,
                hedge_ratio=state.hedge_ratio,
                gross_exposure=state.gross_exposure,
                net_exposure=state.net_exposure,
                kelly_fraction=state.kelly_fraction,
                stop_loss_z_score=state.stop_loss_z_score,
                take_profit_z_score=state.take_profit_z_score,
                max_holding_days=state.max_holding_days,
                notes=list(state.notes),
                updated_at=now,
            )

        symbol_targets = {ticker: 0.0 for ticker in self.symbols}
        for state in self.open_pairs.values():
            half_weight = state.gross_exposure / 2.0
            symbol_targets[state.long_symbol] += half_weight
            symbol_targets[state.short_symbol] -= half_weight

        for intent in cycle.intents:
            symbol_targets[intent.long_symbol] += intent.long_weight
            symbol_targets[intent.short_symbol] += intent.short_weight
            self.open_pairs[intent.pair_id] = PairPositionState(
                pair_id=intent.pair_id,
                cluster_id=intent.cluster_id,
                long_symbol=intent.long_symbol,
                short_symbol=intent.short_symbol,
                opened_at=now,
                status="open",
                entry_z_score=intent.entry_z_score,
                latest_z_score=intent.entry_z_score,
                hedge_ratio=1.0,
                gross_exposure=intent.gross_exposure,
                net_exposure=intent.net_exposure,
                kelly_fraction=intent.kelly_fraction,
                stop_loss_z_score=float(self.strategy["exit_policy"]["initial_stop_loss_z_score"]),
                take_profit_z_score=float(self.strategy["exit_policy"]["initial_take_profit_z_score"]),
                max_holding_days=int(self.strategy["exit_policy"]["max_holding_days"]),
                notes=[intent.decision.rationale],
                updated_at=now,
            )

        set_holdings = getattr(self, "SetHoldings", None)
        liquidate = getattr(self, "Liquidate", None)
        if set_holdings is not None:
            for ticker, weight in symbol_targets.items():
                symbol = self.symbol_registry[ticker]
                if abs(weight) > 1e-6:
                    set_holdings(symbol, weight)
                elif liquidate is not None:
                    liquidate(symbol, "target weight zero")

        self._set_runtime_statistic("OpenPairCount", str(len(self.open_pairs)))
        self._set_runtime_statistic("LastCycleState", "executed" if cycle.intents else "no_new_intents")

    def _set_runtime_statistic(self, key: str, value: str) -> None:
        setter = getattr(self, "SetRuntimeStatistic", None)
        if setter is not None:
            setter(key, value)

    def _publish_filter_runtime_statistics(self, status: Dict[str, Any]) -> None:
        self._set_runtime_statistic("MlConfiguredMode", str(status.get("configured_mode", "embedded_scorecard")))
        self._set_runtime_statistic("MlActiveMode", str(status.get("active_mode", "embedded_scorecard")))
        self._set_runtime_statistic("MlFallbackActive", str(bool(status.get("fallback_active", False))).lower())
        self._set_runtime_statistic("MlLoadStatus", str(status.get("load_status", "unknown")))
        self._set_runtime_statistic("MlModelVersion", str(status.get("loaded_model_version", "")) or "unknown")
        configured_key = str(status.get("configured_model_key", ""))
        self._set_runtime_statistic("MlObjectStoreKey", configured_key or "not_configured")
        self._set_runtime_statistic("MlLoadError", str(status.get("last_error", ""))[:120] or "none")
