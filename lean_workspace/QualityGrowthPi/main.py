"""Cloud-safe LEAN algorithm entrypoint for QualityGrowthPi."""

from __future__ import annotations

import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

PROJECT_DIR = Path(__file__).resolve().parent
UTC = timezone.utc
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import numpy as np

try:
    from AlgorithmImports import *  # type: ignore  # noqa: F401,F403
except ImportError:  # pragma: no cover - local syntax support only
    pass

if "QCAlgorithm" not in globals():  # pragma: no cover - local syntax support only
    class QCAlgorithm:  # noqa: D401
        """Minimal local stub for syntax validation outside LEAN."""

        pass

if "Resolution" not in globals():  # pragma: no cover - local syntax support only
    class Resolution:
        Daily = "Daily"


from scoring import (
    FundamentalSnapshot,
    RebalanceIntent,
    TimingFeatures,
    build_rebalance_intent,
    build_timing_features,
    hash_rebalance_intent,
    load_strategy_config,
    rank_fundamental_candidates,
    stale_data_detected,
)


DAILY_RESOLUTION = getattr(Resolution, "Daily", getattr(Resolution, "DAILY", "Daily"))


class SymbolState:
    """Rolling daily-bar state for timing overlays."""

    def __init__(self, maxlen: int) -> None:
        self.closes = deque(maxlen=maxlen)  # type: Deque[float]
        self.volumes = deque(maxlen=maxlen)  # type: Deque[float]
        self.last_updated = None  # type: Optional[datetime]

    def extend(self, closes: List[float], volumes: List[float], last_updated: Optional[datetime] = None) -> None:
        for close in closes:
            self.closes.append(float(close))
        for volume in volumes:
            self.volumes.append(float(volume))
        if last_updated is not None:
            self.last_updated = last_updated

    def add_bar(self, close: float, volume: float, last_updated: datetime) -> None:
        self.closes.append(float(close))
        self.volumes.append(float(volume))
        self.last_updated = last_updated


def _safe_number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested_attr(obj: Any, path: str, default: Any = None) -> Any:
    current = obj
    for name in path.split("."):
        if current is None:
            return default
        current = getattr(current, name, None)
    return default if current is None else current


def _sector_code(item: Any) -> str | None:
    """Extract Morningstar sector metadata from a LEAN fundamental row."""

    raw = (
        _nested_attr(item, "AssetClassification.MorningstarSectorCode")
        or _nested_attr(item, "AssetClassification.MorningstarSectorCode.Value")
    )
    if raw is None:
        return None
    return str(raw)


class QualityGrowthPiAlgorithm(QCAlgorithm):
    """LEAN wrapper around cloud-safe deterministic strategy helpers."""

    REBALANCE_STATE_KEY = "QualityGrowthPi:last_rebalance_key"

    def Initialize(self) -> None:  # noqa: N802
        self.config = load_strategy_config(PROJECT_DIR / "config.py")
        self.strategy = self.config["strategy"]
        self.runtime = self.config.get("runtime", {})
        self.audit_enabled = bool(self.runtime.get("cloud_audit_logging", True))

        self.current_fundamentals = {}  # type: Dict[str, FundamentalSnapshot]
        self.symbol_registry = {}  # type: Dict[str, Any]
        self.symbol_state = {}  # type: Dict[str, SymbolState]
        self.timing_features = {}  # type: Dict[str, TimingFeatures]
        self.last_rebalance_key = None  # type: Optional[str]

        start_date = datetime.strptime(str(self.runtime.get("backtest_start_date", "2018-01-01")), "%Y-%m-%d")
        if hasattr(self, "SetStartDate"):
            self.SetStartDate(start_date.year, start_date.month, start_date.day)
        if hasattr(self, "SetCash"):
            self.SetCash(float(self.runtime.get("initial_cash", 100_000.0)))

        if hasattr(self, "UniverseSettings"):
            self.UniverseSettings.Resolution = DAILY_RESOLUTION

        anchor_ticker = self.strategy["rebalance"]["anchor_symbol"]
        benchmark_ticker = self.strategy.get("benchmark_symbol", anchor_ticker)
        self.anchor_symbol = anchor_ticker
        self.benchmark_symbol = benchmark_ticker
        if hasattr(self, "AddEquity"):
            self.anchor_symbol = self.AddEquity(anchor_ticker, DAILY_RESOLUTION).Symbol
            if benchmark_ticker == anchor_ticker:
                self.benchmark_symbol = self.anchor_symbol
            else:
                self.benchmark_symbol = self.AddEquity(benchmark_ticker, DAILY_RESOLUTION).Symbol
        if hasattr(self, "SetBenchmark"):
            self.SetBenchmark(self.benchmark_symbol)

        if hasattr(self, "AddUniverse"):
            self.AddUniverse(self.FundamentalSelectionFunction)

        if hasattr(self, "Schedule") and hasattr(self, "DateRules") and hasattr(self, "TimeRules"):
            self.Schedule.On(
                self.DateRules.EveryDay(self.anchor_symbol),
                self.TimeRules.AfterMarketOpen(self.anchor_symbol, int(self.strategy["rebalance"]["after_open_minutes"])),
                self.Rebalance,
            )

        self._emit_audit(
            "initialize",
            {
                "algorithm": self.strategy["algorithm_name"],
                "anchor_symbol": str(self.anchor_symbol),
                "benchmark_symbol": str(self.benchmark_symbol),
                "max_holdings": int(self.strategy["rebalance"]["max_holdings"]),
                "llm_mode": "observe_only",
            },
        )
        self._set_runtime_statistic("LastRebalanceCheckState", "initialized")
        self._set_runtime_statistic("LastUniverseCurrentFundamentals", "0")
        self._set_runtime_statistic("LastTimingFeatureCount", "0")
        self._set_runtime_statistic("LastRebalancePendingPriceCount", "0")

    def CoarseSelectionFunction(self, coarse):  # noqa: N802
        """Initial coarse filter to reduce fine universe load."""

        return [item.Symbol for item in self._filter_fundamentals(coarse)]

    def FundamentalSelectionFunction(self, fundamentals):  # noqa: N802
        """Single-stage fundamental universe selection for current LEAN APIs."""

        filtered = self._filter_fundamentals(fundamentals)
        return self._rank_and_select(filtered)

    def FineSelectionFunction(self, fine):  # noqa: N802
        """Fine fundamental selection using the local pure ranking logic."""

        return self._rank_and_select(fine)

    def _filter_fundamentals(self, fundamentals) -> List[Any]:
        """Apply the former coarse universe filter to fundamental rows."""

        min_price = float(self.strategy["universe"]["min_price"])
        filtered = []
        for item in fundamentals:
            has_fundamentals = bool(getattr(item, "HasFundamentalData", False))
            price = _safe_number(getattr(item, "Price", None), 0.0) or 0.0
            dollar_volume = _safe_number(getattr(item, "DollarVolume", None), 0.0) or 0.0
            volume = _safe_number(getattr(item, "Volume", None))
            if (volume is None or volume <= 0) and price > 0 and dollar_volume > 0:
                volume = dollar_volume / price
            volume = volume or 0.0
            if not has_fundamentals or price <= min_price or volume <= 0:
                continue
            if dollar_volume <= 0:
                dollar_volume = price * volume
            filtered.append((item, dollar_volume))
        filtered.sort(key=lambda row: row[1], reverse=True)
        fine_universe_limit = max(1, int(self.runtime.get("fine_universe_limit", 1000)))
        return [item for item, _ in filtered[:fine_universe_limit]]

    def _rank_and_select(self, fundamentals) -> List[Any]:
        """Rank shortlisted fundamentals and return LEAN symbols."""
        snapshots = []  # type: List[FundamentalSnapshot]
        for item in fundamentals:
            symbol_str = str(item.Symbol)
            self.symbol_registry[symbol_str] = item.Symbol
            snapshots.append(
                FundamentalSnapshot(
                    symbol=symbol_str,
                    as_of=datetime.now(UTC),
                    has_fundamental_data=True,
                    market_cap=_safe_number(getattr(item, "MarketCap", None), 0.0) or 0.0,
                    exchange_id=str(_nested_attr(item, "CompanyReference.PrimaryExchangeID", "")),
                    price=_safe_number(getattr(item, "Price", None), 0.0) or 0.0,
                    volume=_safe_number(getattr(item, "Volume", None), 0.0) or 0.0,
                    sector_code=_sector_code(item),
                    roe=_safe_number(_nested_attr(item, "OperationRatios.ROE.Value")),
                    gross_margin=_safe_number(_nested_attr(item, "OperationRatios.GrossMargin.Value")),
                    debt_to_equity=_safe_number(_nested_attr(item, "OperationRatios.TotalDebtEquityRatio.Value")),
                    revenue_growth=_safe_number(_nested_attr(item, "OperationRatios.RevenueGrowth.Value")),
                    net_income_growth=_safe_number(_nested_attr(item, "OperationRatios.NetIncomeGrowth.Value")),
                    pe_ratio=_safe_number(_nested_attr(item, "ValuationRatios.PERatio")),
                    peg_ratio=_safe_number(_nested_attr(item, "ValuationRatios.PEGRatio")),
                )
            )

        ranked = rank_fundamental_candidates(snapshots, self.config)
        pool_size = int(self.strategy["rebalance"]["max_holdings"]) * int(
            self.strategy["rebalance"]["candidate_pool_multiplier"]
        )
        shortlisted = ranked[:pool_size]
        shortlisted_symbols = {candidate.symbol for candidate in shortlisted}
        self.current_fundamentals = {
            snapshot.symbol: snapshot for snapshot in snapshots if snapshot.symbol in shortlisted_symbols
        }
        self._emit_audit(
            "universe_selection",
            {
                "fine_count": len(snapshots),
                "ranked_count": len(ranked),
                "shortlisted_count": len(shortlisted_symbols),
                "selected_symbols": sorted(shortlisted_symbols),
                "diagnostics": self._fundamental_diagnostics(snapshots),
            },
        )
        self._set_runtime_statistic("LastUniverseSelectionAt", self._runtime_stamp())
        self._set_runtime_statistic("LastUniverseFineCount", str(len(snapshots)))
        self._set_runtime_statistic("LastUniverseRankedCount", str(len(ranked)))
        self._set_runtime_statistic("LastUniverseShortlistedCount", str(len(shortlisted_symbols)))
        self._set_runtime_statistic("LastUniverseCurrentFundamentals", str(len(self.current_fundamentals)))
        diagnostics = self._fundamental_diagnostics(snapshots)
        self._set_runtime_statistic("LastUniverseDiagExchange", str(diagnostics["exchange_match_count"]))
        self._set_runtime_statistic("LastUniverseDiagROE", str(diagnostics["roe_threshold_count"]))
        self._set_runtime_statistic("LastUniverseDiagPEG", str(diagnostics["peg_threshold_count"]))
        return [item.Symbol for item in fundamentals if str(item.Symbol) in shortlisted_symbols]

    def OnSecuritiesChanged(self, changes) -> None:  # noqa: N802
        """Bootstrap timing history for newly added symbols and prune removed entries."""

        added = getattr(changes, "AddedSecurities", [])
        removed = getattr(changes, "RemovedSecurities", [])
        for security in added:
            symbol = getattr(security, "Symbol", security)
            symbol_str = str(symbol)
            self.symbol_registry[symbol_str] = symbol
            try:
                self._bootstrap_timing(symbol)
            except Exception as exc:  # pragma: no cover - LEAN runtime branch
                self._emit_audit("timing_bootstrap_failed", {"symbol": symbol_str, "error": str(exc)})
        for security in removed:
            symbol = getattr(security, "Symbol", security)
            symbol_str = str(symbol)
            self.symbol_state.pop(symbol_str, None)
            self.timing_features.pop(symbol_str, None)

    def OnData(self, data) -> None:  # noqa: N802
        """Update daily timing state for tracked securities."""

        bars = getattr(data, "Bars", None)
        if bars is None:
            return
        tracked_symbols = set(self.current_fundamentals) | set(self.symbol_state)
        for symbol_str in list(tracked_symbols):
            lean_symbol = self.symbol_registry.get(symbol_str)
            if lean_symbol is None:
                continue
            if hasattr(bars, "ContainsKey") and not bars.ContainsKey(lean_symbol):
                continue
            try:
                bar = bars[lean_symbol]
            except Exception:
                continue
            state = self._ensure_symbol_state(symbol_str)
            last_updated = getattr(bar, "EndTime", None) or getattr(self, "Time", None) or datetime.now(UTC)
            state.add_bar(float(bar.Close), float(bar.Volume), last_updated)
            self.timing_features[symbol_str] = build_timing_features(
                symbol_str,
                list(state.closes),
                list(state.volumes),
                self.config,
                last_updated=state.last_updated,
            )
        self._set_runtime_statistic("LastTimingUpdateAt", self._runtime_stamp())
        self._set_runtime_statistic("LastTimingFeatureCount", str(len(self.timing_features)))

    def _ensure_symbol_state(self, symbol: str) -> SymbolState:
        maxlen = max(
            int(self.strategy["timing"]["long_sma"]),
            int(self.runtime.get("bootstrap_history_days", 35)),
            int(self.strategy["timing"]["price_window"]),
            int(self.strategy["timing"]["volume_window"]),
        )
        state = self.symbol_state.get(symbol)
        if state is None:
            state = SymbolState(maxlen=maxlen)
            self.symbol_state[symbol] = state
        return state

    def _bootstrap_timing(self, symbol: Any) -> None:
        symbol_str = str(symbol)
        state = self._ensure_symbol_state(symbol_str)
        history_days = max(
            int(self.strategy["timing"]["long_sma"]),
            int(self.runtime.get("bootstrap_history_days", 35)),
        )
        history_fn = getattr(self, "History", None)
        if history_fn is None:
            return
        history = history_fn(symbol, history_days, DAILY_RESOLUTION)
        closes = []  # type: List[float]
        volumes = []  # type: List[float]
        if history is not None:
            try:
                if hasattr(history, "columns"):
                    close_series = history["close"]
                    volume_series = history["volume"]
                    closes = [float(value) for value in list(close_series)]
                    volumes = [float(value) for value in list(volume_series)]
                else:
                    bars = list(history)
                    closes = [float(getattr(bar, "Close", 0.0)) for bar in bars]
                    volumes = [float(getattr(bar, "Volume", 0.0)) for bar in bars]
            except Exception:
                closes = []
                volumes = []
        state.extend(closes, volumes, getattr(self, "Time", None) or datetime.now(UTC))
        self.timing_features[symbol_str] = build_timing_features(
            symbol_str,
            list(state.closes),
            list(state.volumes),
            self.config,
            last_updated=state.last_updated,
        )

    def _rebalance_key(self) -> str:
        current_time = getattr(self, "Time", None) or datetime.now(UTC)
        frequency = str(self.strategy["rebalance"].get("frequency", "daily")).strip().lower()
        if frequency == "monthly":
            cadence_key = current_time.strftime("%Y-%m")
        else:
            cadence_key = current_time.strftime("%Y-%m-%d")
        return f"{self.strategy['algorithm_name']}:{cadence_key}"

    def _has_completed_rebalance(self, rebalance_key: str) -> bool:
        if self.last_rebalance_key == rebalance_key:
            return True
        object_store = getattr(self, "ObjectStore", None)
        if object_store is not None:
            try:
                if object_store.ContainsKey(self.REBALANCE_STATE_KEY):
                    return object_store.Read(self.REBALANCE_STATE_KEY) == rebalance_key
            except Exception:
                return False
        return False

    def _mark_rebalance_completed(self, rebalance_key: str) -> None:
        self.last_rebalance_key = rebalance_key
        object_store = getattr(self, "ObjectStore", None)
        if object_store is not None:
            try:
                object_store.Save(self.REBALANCE_STATE_KEY, rebalance_key)
            except Exception:
                pass

    def Rebalance(self) -> None:  # noqa: N802
        """Construct target weights with restart-safe idempotency."""

        rebalance_key = self._rebalance_key()
        if self._has_completed_rebalance(rebalance_key):
            self._set_runtime_statistic("LastRebalanceCheckAt", self._runtime_stamp())
            self._set_runtime_statistic("LastRebalanceCheckKey", rebalance_key)
            self._set_runtime_statistic("LastRebalanceCheckState", "already_completed")
            self._emit_audit("rebalance_skip", {"rebalance_key": rebalance_key, "reason": "already_completed"})
            return

        if not self.current_fundamentals:
            self._set_runtime_statistic("LastRebalanceCheckAt", self._runtime_stamp())
            self._set_runtime_statistic("LastRebalanceCheckKey", rebalance_key)
            self._set_runtime_statistic("LastRebalanceCheckState", "no_current_fundamentals")
            self._emit_audit(
                "rebalance_deferred",
                {
                    "rebalance_key": rebalance_key,
                    "reason": "no_current_fundamentals",
                    "timing_feature_count": len(self.timing_features),
                },
            )
            return

        stale_symbols = [
            symbol
            for symbol, features in self.timing_features.items()
            if stale_data_detected(
                features.last_updated,
                int(self.runtime.get("stale_data_max_age_minutes", 30)),
                now=getattr(self, "Time", None) or datetime.now(UTC),
            )
        ]
        if stale_symbols:
            self._set_runtime_statistic("LastRebalanceCheckAt", self._runtime_stamp())
            self._set_runtime_statistic("LastRebalanceCheckKey", rebalance_key)
            self._set_runtime_statistic("LastRebalanceCheckState", "stale_data")
            self._set_runtime_statistic("LastRebalanceStaleSymbolCount", str(len(stale_symbols)))
            self._emit_audit(
                "rebalance_skip",
                {"rebalance_key": rebalance_key, "reason": "stale_data", "symbols": stale_symbols},
            )
            return

        intent = build_rebalance_intent(
            rebalance_key=rebalance_key,
            snapshots=self.current_fundamentals.values(),
            timing_map=self.timing_features,
            config=self.config,
            already_filtered=True,
        )
        if not intent.target_weights:
            self._set_runtime_statistic("LastRebalanceCheckAt", self._runtime_stamp())
            self._set_runtime_statistic("LastRebalanceCheckKey", rebalance_key)
            self._set_runtime_statistic("LastRebalanceCheckState", "empty_targets")
            self._set_runtime_statistic("LastRebalanceCandidateCount", str(len(intent.scored_candidates)))
            self._set_runtime_statistic("LastRebalanceTargetCount", "0")
            self._emit_audit(
                "rebalance_deferred",
                {
                    "rebalance_key": rebalance_key,
                    "reason": "empty_targets",
                    "candidate_count": len(intent.scored_candidates),
                    "current_fundamental_count": len(self.current_fundamentals),
                    "timing_feature_count": len(self.timing_features),
                },
            )
            return
        self._set_runtime_statistic("LastRebalanceCheckAt", self._runtime_stamp())
        self._set_runtime_statistic("LastRebalanceCheckKey", rebalance_key)
        self._set_runtime_statistic("LastRebalanceCheckState", "intent_ready")
        self._set_runtime_statistic("LastRebalanceCandidateCount", str(len(intent.scored_candidates)))
        self._set_runtime_statistic("LastRebalanceTargetCount", str(len(intent.target_weights)))
        pending_symbols = self._pending_trade_symbols(set(intent.target_weights))
        if pending_symbols:
            self._set_runtime_statistic("LastRebalanceCheckState", "pending_prices")
            self._set_runtime_statistic("LastRebalancePendingPriceCount", str(len(pending_symbols)))
            self._emit_audit(
                "rebalance_deferred",
                {
                    "rebalance_key": rebalance_key,
                    "reason": "pending_prices",
                    "symbols": pending_symbols,
                    "candidate_count": len(intent.scored_candidates),
                    "target_count": len(intent.target_weights),
                },
            )
            return
        self._emit_rebalance_intent(intent)
        self._apply_targets(intent)
        self._mark_rebalance_completed(rebalance_key)
        self._set_runtime_statistic("LastRebalanceCheckState", "executed")
        self._set_runtime_statistic("LastRebalancePendingPriceCount", "0")
        self._set_runtime_statistic("LastSuccessfulRebalanceAt", self._runtime_stamp())
        self._set_runtime_statistic("LastSuccessfulRebalanceKey", rebalance_key)
        self._set_runtime_statistic("LastSuccessfulTargetCount", str(len(intent.target_weights)))

    def _apply_targets(self, intent: RebalanceIntent) -> None:
        target_symbols = set(intent.target_weights)

        if hasattr(self, "Portfolio"):
            for symbol_str, lean_symbol in list(self.symbol_registry.items()):
                try:
                    holding = self.Portfolio[lean_symbol]
                except Exception:
                    continue
                if getattr(holding, "Invested", False) and symbol_str not in target_symbols:
                    liquidate = getattr(self, "Liquidate", None)
                    if liquidate is not None:
                        liquidate(lean_symbol, "QualityGrowthPi deselection")

        for symbol_str, weight in intent.target_weights.items():
            target_symbol = self.symbol_registry.get(symbol_str, symbol_str)
            set_holdings = getattr(self, "SetHoldings", None)
            if set_holdings is not None:
                set_holdings(target_symbol, float(weight))

    def _pending_trade_symbols(self, target_symbols: set[str]) -> List[str]:
        """Return symbols that are selected for action but still lack a tradable price."""

        symbols_to_trade = set(target_symbols)
        if hasattr(self, "Portfolio"):
            for symbol_str, lean_symbol in list(self.symbol_registry.items()):
                try:
                    holding = self.Portfolio[lean_symbol]
                except Exception:
                    continue
                if getattr(holding, "Invested", False) and symbol_str not in target_symbols:
                    symbols_to_trade.add(symbol_str)
        pending = []
        for symbol_str in sorted(symbols_to_trade):
            lean_symbol = self.symbol_registry.get(symbol_str)
            if lean_symbol is None or not self._security_has_accurate_price(lean_symbol):
                pending.append(symbol_str)
        return pending

    def _security_has_accurate_price(self, lean_symbol: Any) -> bool:
        """Check whether LEAN has received a reliable tradable price for a security."""

        securities = getattr(self, "Securities", None)
        if securities is None:
            return True
        try:
            security = securities[lean_symbol]
        except Exception:
            return False
        if not bool(getattr(security, "IsTradable", True)):
            return False
        if not bool(getattr(security, "HasData", False)):
            return False
        return (_safe_number(getattr(security, "Price", None), 0.0) or 0.0) > 0.0

    def _emit_rebalance_intent(self, intent: RebalanceIntent) -> None:
        self._emit_audit(
            "rebalance_intent",
            {
                "rebalance_key": intent.rebalance_key,
                "selected_symbols": intent.selected_symbols,
                "target_weights": intent.target_weights,
                "candidate_count": len(intent.scored_candidates),
                "intent_hash": hash_rebalance_intent(intent),
            },
        )

    def OnOrderEvent(self, orderEvent) -> None:  # noqa: N802
        """Emit structured order event logs."""

        status = str(getattr(orderEvent, "Status", ""))
        if status not in {"Filled", "PartiallyFilled", "Canceled", "Invalid"}:
            return
        self._emit_audit(
            "order_event",
            {
                "symbol": str(getattr(orderEvent, "Symbol", "")),
                "status": status,
                "fill_price": _safe_number(getattr(orderEvent, "FillPrice", None)),
                "fill_quantity": _safe_number(getattr(orderEvent, "FillQuantity", None)),
            },
        )

    def _emit_audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.audit_enabled:
            return
        encoded = json.dumps(
            {
                "event_type": event_type,
                "payload": payload,
                "ts": (getattr(self, "Time", None) or datetime.now(UTC)).isoformat(),
            },
            sort_keys=True,
            default=str,
        )
        if hasattr(self, "Log"):
            self.Log(encoded)

    def _set_runtime_statistic(self, key: str, value: str) -> None:
        setter = getattr(self, "SetRuntimeStatistic", None)
        if setter is not None:
            try:
                setter(key, value)
            except Exception:
                pass

    def _runtime_stamp(self) -> str:
        return (getattr(self, "Time", None) or datetime.now(UTC)).isoformat()

    def _fundamental_diagnostics(self, snapshots: List[FundamentalSnapshot]) -> Dict[str, Any]:
        thresholds = self.strategy["thresholds"]
        universe = self.strategy["universe"]
        return {
            "exchange_match_count": sum(snapshot.exchange_id == str(universe["exchange_id"]) for snapshot in snapshots),
            "min_market_cap_count": sum(
                snapshot.market_cap > float(universe["min_market_cap"]) for snapshot in snapshots
            ),
            "min_price_count": sum(snapshot.price > float(universe["min_price"]) for snapshot in snapshots),
            "positive_volume_count": sum(snapshot.volume > 0 for snapshot in snapshots),
            "roe_threshold_count": sum(
                snapshot.roe is not None and snapshot.roe >= float(thresholds["roe_min"]) for snapshot in snapshots
            ),
            "gross_margin_threshold_count": sum(
                snapshot.gross_margin is not None and snapshot.gross_margin >= float(thresholds["gross_margin_min"])
                for snapshot in snapshots
            ),
            "debt_to_equity_threshold_count": sum(
                snapshot.debt_to_equity is not None
                and float(thresholds["debt_to_equity_min"]) < snapshot.debt_to_equity <= float(thresholds["debt_to_equity_max"])
                for snapshot in snapshots
            ),
            "revenue_growth_threshold_count": sum(
                snapshot.revenue_growth is not None
                and snapshot.revenue_growth >= float(thresholds["revenue_growth_min"])
                for snapshot in snapshots
            ),
            "net_income_growth_threshold_count": sum(
                snapshot.net_income_growth is None
                or snapshot.net_income_growth == 0
                or snapshot.net_income_growth >= float(thresholds["net_income_growth_min"])
                for snapshot in snapshots
            ),
            "positive_pe_count": sum(
                snapshot.pe_ratio is not None and snapshot.pe_ratio > float(thresholds["pe_ratio_min"])
                for snapshot in snapshots
            ),
            "peg_threshold_count": sum(
                snapshot.peg_ratio is not None
                and float(thresholds["peg_ratio_min"]) < snapshot.peg_ratio <= float(thresholds["peg_ratio_max"])
                for snapshot in snapshots
            ),
            "sector_code_count": sum(snapshot.sector_code is not None for snapshot in snapshots),
        }
