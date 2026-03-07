"""LEAN algorithm entrypoint for the shared quality-growth strategy."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from AlgorithmImports import *  # type: ignore  # noqa: F401,F403
except ImportError:  # pragma: no cover - local syntax support only
    class QCAlgorithm:  # noqa: D401
        """Minimal local stub for syntax validation outside LEAN."""

        pass

    class Resolution:
        Daily = "Daily"

    class PortfolioTarget:
        def __init__(self, symbol: str, quantity: float) -> None:
            self.Symbol = symbol
            self.Quantity = quantity

    class SecurityChanges:
        AddedSecurities: list[Any] = []


from src.audit import AuditLogger
from src.health import stale_data_detected
from src.logging_utils import configure_logging, get_logger
from src.models import AuditEvent, DeterministicDecisionContext, FundamentalSnapshot, LLMMode
from src.scoring import build_rebalance_intent, hash_rebalance_intent, rank_fundamental_candidates
from src.settings import load_settings
from src.state_store import StateStore
from src.timing import build_timing_features


def _safe_number(value: Any, default: float | None = None) -> float | None:
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


class QualityGrowthPiAlgorithm(QCAlgorithm):
    """LEAN wrapper around shared deterministic strategy modules."""

    def Initialize(self) -> None:  # noqa: N802 - LEAN naming
        self.settings = load_settings(PROJECT_ROOT)
        configure_logging(self.settings)
        self.logger = get_logger("quant_gpt")
        self.state_store = StateStore(self.settings.state_db_path)
        self.state_store.initialize()
        self.audit = AuditLogger(store=self.state_store)

        self.strategy = self.settings.strategy
        self.current_fundamentals: dict[str, FundamentalSnapshot] = {}
        self.timing_state = {}
        self.last_rebalance_key: str | None = None

        if hasattr(self, "SetStartDate"):
            self.SetStartDate(2018, 1, 1)
        if hasattr(self, "SetCash"):
            self.SetCash(100000)

        self.anchor_symbol = "SPY"
        if hasattr(self, "AddEquity"):
            self.anchor_symbol = self.AddEquity("SPY", Resolution.Daily).Symbol

        if hasattr(self, "AddUniverse"):
            self.AddUniverse(self.CoarseSelectionFunction, self.FineSelectionFunction)

        if hasattr(self, "Schedule") and hasattr(self, "DateRules") and hasattr(self, "TimeRules"):
            self.Schedule.On(
                self.DateRules.MonthStart(self.anchor_symbol),
                self.TimeRules.AfterMarketOpen(self.anchor_symbol, self.strategy.rebalance.after_open_minutes),
                self.Rebalance,
            )

        self.audit.emit(
            AuditEvent(
                event_type="lean_initialize",
                payload={
                    "anchor_symbol": str(self.anchor_symbol),
                    "llm_mode": self.settings.runtime.llm_mode.value,
                    "provider_mode": self.settings.runtime.provider_mode.value,
                },
            )
        )

    def CoarseSelectionFunction(self, coarse):  # noqa: N802 - LEAN naming
        """Initial coarse filter to reduce fine universe load."""

        selected = []
        for item in coarse:
            has_fundamentals = bool(getattr(item, "HasFundamentalData", False))
            price = _safe_number(getattr(item, "Price", None), 0.0) or 0.0
            if not has_fundamentals or price <= self.strategy.universe.min_price:
                continue
            selected.append(item.Symbol)
        return selected[:500]

    def FineSelectionFunction(self, fine):  # noqa: N802 - LEAN naming
        """Fine fundamental selection using the shared pure ranking logic."""

        snapshots: list[FundamentalSnapshot] = []
        for item in fine:
            snapshot = FundamentalSnapshot(
                symbol=str(item.Symbol),
                as_of=datetime.now(UTC),
                has_fundamental_data=True,
                market_cap=_safe_number(getattr(item, "MarketCap", None), 0.0) or 0.0,
                exchange_id=str(_nested_attr(item, "CompanyReference.PrimaryExchangeID", "")),
                price=_safe_number(getattr(item, "Price", None), 0.0) or 0.0,
                volume=_safe_number(getattr(item, "Volume", None), 0.0) or 0.0,
                roe=_safe_number(_nested_attr(item, "OperationRatios.ROE.Value")),
                gross_margin=_safe_number(_nested_attr(item, "OperationRatios.GrossMargin.Value")),
                debt_to_equity=_safe_number(_nested_attr(item, "OperationRatios.TotalDebtEquityRatio.Value")),
                revenue_growth=_safe_number(_nested_attr(item, "OperationRatios.RevenueGrowth.Value")),
                net_income_growth=_safe_number(_nested_attr(item, "OperationRatios.NetIncomeGrowth.Value")),
                pe_ratio=_safe_number(_nested_attr(item, "ValuationRatios.PERatio")),
                peg_ratio=_safe_number(_nested_attr(item, "ValuationRatios.PEGRatio")),
            )
            snapshots.append(snapshot)

        ranked = rank_fundamental_candidates(snapshots, self.strategy)
        pool_size = self.strategy.rebalance.max_holdings * self.strategy.rebalance.candidate_pool_multiplier
        shortlisted = ranked[:pool_size]
        shortlisted_symbols = {candidate.symbol for candidate in shortlisted}
        self.current_fundamentals = {
            snapshot.symbol: snapshot for snapshot in snapshots if snapshot.symbol in shortlisted_symbols
        }
        return [item.Symbol for item in fine if str(item.Symbol) in shortlisted_symbols]

    def OnSecuritiesChanged(self, changes) -> None:  # noqa: N802 - LEAN naming
        """Bootstrap timing history for newly added symbols."""

        added = getattr(changes, "AddedSecurities", [])
        for security in added:
            symbol = str(getattr(security, "Symbol", security))
            try:
                self.timing_state[symbol] = self._bootstrap_timing(symbol)
            except Exception as exc:  # pragma: no cover - LEAN runtime branch
                self.logger.warning("timing bootstrap failed for %s: %s", symbol, exc)

    def _bootstrap_timing(self, symbol: str):
        history_days = max(self.strategy.timing.long_sma, self.settings.execution.bootstrap_history_days)
        if not hasattr(self, "History"):
            return build_timing_features(symbol, [], [], self.strategy)
        history = self.History(symbol, history_days, Resolution.Daily)
        closes: list[float] = []
        volumes: list[float] = []
        if history is not None:
            try:
                if hasattr(history, "loc"):
                    symbol_history = history.loc[str(symbol)]
                    closes = [float(value) for value in symbol_history["close"].tolist()]
                    volumes = [float(value) for value in symbol_history["volume"].tolist()]
            except Exception:
                try:
                    closes = [float(bar.Close) for bar in history]
                    volumes = [float(bar.Volume) for bar in history]
                except Exception:
                    closes = []
                    volumes = []
        return build_timing_features(symbol, closes, volumes, self.strategy)

    def Rebalance(self) -> None:  # noqa: N802 - LEAN naming
        """Construct target weights with restart-safe idempotency."""

        rebalance_key = f"{self.strategy.algorithm_name}:{self.Time.strftime('%Y-%m')}" if hasattr(self, "Time") else (
            f"{self.strategy.algorithm_name}:{datetime.now(UTC).strftime('%Y-%m')}"
        )
        self.last_rebalance_key = rebalance_key
        if self.state_store.has_rebalance(rebalance_key):
            self.logger.info("rebalance skip key=%s reason=already_completed", rebalance_key)
            return

        stale_symbols = [
            symbol
            for symbol, state in self.timing_state.items()
            if stale_data_detected(state.last_updated, self.settings.execution.stale_data_max_age_minutes)
        ]
        if stale_symbols:
            self.logger.warning("rebalance skip key=%s reason=stale_data symbols=%s", rebalance_key, stale_symbols)
            return

        intent = build_rebalance_intent(
            rebalance_key=rebalance_key,
            snapshots=self.current_fundamentals.values(),
            timing_map=self.timing_state,
            strategy=self.strategy,
        )
        intent_hash = hash_rebalance_intent(intent)
        if not self.state_store.mark_rebalance_started(
            rebalance_key=rebalance_key,
            intent_hash=intent_hash,
            metadata={"selected_symbols": intent.selected_symbols},
        ):
            self.logger.info("rebalance already started key=%s", rebalance_key)
            return

        self.audit.emit(
            AuditEvent(
                event_type="rebalance_intent",
                payload={
                    "rebalance_key": rebalance_key,
                    "selected_symbols": intent.selected_symbols,
                    "target_weights": intent.target_weights,
                    "candidate_count": len(intent.scored_candidates),
                },
            )
        )

        if hasattr(self, "SetHoldings"):
            for symbol, weight in intent.target_weights.items():
                self.SetHoldings(symbol, weight)

        self.state_store.mark_rebalance_completed(rebalance_key, metadata={"intent_hash": intent_hash})

    def OnOrderEvent(self, orderEvent) -> None:  # noqa: N802 - LEAN naming
        """Persist structured order event logs."""

        self.audit.emit(
            AuditEvent(
                event_type="order_event",
                payload={
                    "symbol": str(getattr(orderEvent, "Symbol", "")),
                    "status": str(getattr(orderEvent, "Status", "")),
                    "fill_price": _safe_number(getattr(orderEvent, "FillPrice", None)),
                    "fill_quantity": _safe_number(getattr(orderEvent, "FillQuantity", None)),
                },
            )
        )
