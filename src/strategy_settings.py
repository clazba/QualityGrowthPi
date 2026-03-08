"""Single source of truth for strategy parameters that move backtest outputs.

This module replaces scattered YAML values and LEAN-only constants for the
strategy math. Each parameter is documented at the definition site with:

- expected type and practical range
- the primary backtest metrics it moves
- the causal reason the metric changes when the parameter changes

Two strategy families are exposed:

- ``quality_growth``: the validated long-only factor strategy
- ``stat_arb_graph_pairs``: a daily graph-clustered statistical arbitrage stack

Profiles:

- ``default``: the production / validated strategy profile
- ``short_regression``: same math with a shorter backtest horizon for faster iteration
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class ProfitabilitySettings:
    """Thresholds that bias the portfolio toward higher-quality earnings power."""

    # float in [0, 1+]. Higher ROE floors usually improve Average Win,
    # Expectancy, and Net Profit if capital efficiency is predictive, but they
    # also shrink LastUniverseRankedCount and Total Orders by excluding more names.
    roe_min: float = 0.15

    # float in [0, 1+]. Higher gross-margin floors favor pricing power and
    # operating resilience, which can improve Profit-Loss Ratio and Win Rate,
    # but can reduce diversification and raise Drawdown if the universe gets too thin.
    gross_margin_min: float = 0.30

    # float in [0, 1+]. Higher revenue growth floors increase exposure to fast
    # growers and can lift Return / CAGR, but also increase turnover and fees
    # when growth leadership rotates.
    revenue_growth_min: float = 0.10

    # float in [0, 1+]. Higher earnings-growth floors improve fundamental
    # momentum quality and can raise Average Win / Net Profit, but reduce
    # eligible names and can lower capacity in weak macro regimes.
    net_income_growth_min: float = 0.10

    # float >= 0.0. Raising the minimum PE removes distressed / lossmaking names,
    # which can reduce left-tail risk and improve Drawdown, but can also exclude
    # early recoveries that boost Alpha.
    pe_ratio_min: float = 5.0

    # float >= 0.0. Raising the minimum PEG removes invalid or negative-growth
    # valuation artifacts. Too high a floor can reduce candidate breadth and
    # therefore lower Total Orders and Return opportunity.
    peg_ratio_min: float = 0.0

    # float > peg_ratio_min. Lowering this cap makes the strategy more valuation
    # sensitive, which can reduce Drawdown / Beta, but may also cut CAGR if high-
    # momentum expensive winners are filtered out too early.
    peg_ratio_max: float = 2.0


@dataclass(frozen=True)
class TradeMechanicsSettings:
    """Portfolio construction and market-access parameters."""

    # str. LEAN rebalance cadence switch; "daily" increases Total Orders,
    # Fees, and Turnover while reacting faster to new signals. "monthly"
    # lowers costs but increases lag.
    frequency: str = "weekly"

    # str ticker. Used to anchor schedule timing; moving to a less liquid or
    # non-US symbol can distort rebalance timing and therefore Fees / slippage.
    anchor_symbol: str = "SPY"

    # int >= 0 minutes after the open. Later execution usually lowers pending-price
    # skips and trade rejections, but can miss early moves and reduce Alpha.
    after_open_minutes: int = 30

    # int > 0. More holdings reduce idiosyncratic drawdown and Beta, but dilute
    # conviction, lower Average Win, and raise Total Orders / Fees.
    max_holdings: int = 10

    # int >= 1. A larger candidate pool gives the timing model more choice and can
    # improve Sharpe / Sortino, but increases turnover and the chance of marginal names.
    candidate_pool_multiplier: int = 3

    # str exchange code. Narrower exchange scope reduces operational complexity,
    # but can lower opportunity count and Total Orders.
    exchange_id: str = "NYS"

    # float >= 0. Larger market-cap floors usually improve capacity and reduce
    # tail risk, but can suppress Alpha by removing smaller, faster-growing names.
    min_market_cap: float = 5_000_000_000

    # float > 0. Higher price floors reduce microstructure noise and tiny-share
    # order issues, often helping Fees and fill quality, but may lower Return opportunity.
    min_price: float = 10.0

    # bool. Requiring fundamentals improves ranking consistency and usually helps
    # Sharpe / Expectancy, but reduces the breadth of the tradable universe.
    require_fundamental_data: bool = True

    # int > 0. Coarse/fundamental universe cap before ranking. Increasing this can
    # improve Alpha by broadening the search, but increases processing, turnover,
    # and may lower capacity if the tail names are illiquid.
    fine_universe_limit: int = 1000


@dataclass(frozen=True)
class RiskVolatilitySettings:
    """Parameters that govern leverage tolerance and the timing overlay."""

    # float >= 0. Lower debt floors are rarely binding; higher minimum leverage
    # floors would mechanically increase financial risk and Drawdown.
    debt_to_equity_min: float = 0.0

    # float > debt_to_equity_min. Lowering this cap reduces balance-sheet risk
    # and can improve Drawdown / Sortino, but may reduce universe breadth.
    debt_to_equity_max: float = 1.5

    # int >= 2. Longer windows smooth relative-volume noise, which can reduce
    # Turnover and Fees, but also delay signal response.
    volume_window: int = 20

    # int >= 4. Longer price windows stabilize volatility estimates and can
    # improve Sharpe, but may react too slowly to regime shifts.
    price_window: int = 20

    # int > 0 and < long_sma. Shorter SMAs react faster, which can improve Return
    # in trends but also increase false positives and Turnover.
    short_sma: int = 20

    # int > short_sma. Longer SMAs improve trend confirmation and may reduce
    # Drawdown, but increase entry lag and can lower CAGR.
    long_sma: int = 100

    # float >= 0. Higher thresholds demand stronger participation before entry,
    # which can raise Average Win but reduce signal count and Total Orders.
    relative_volume_threshold: float = 1.2

    # float >= 0. Lower thresholds require tighter volatility contraction, which
    # can improve risk-adjusted entries but reduce candidate count.
    volatility_contraction_threshold: float = 0.75


@dataclass(frozen=True)
class QuantScoreSettings:
    """Relative ranking weights that drive factor exposure and risk-adjusted returns."""

    # str ticker. The benchmark directly changes Alpha, Beta, Information Ratio,
    # Tracking Error, and Treynor/Sharpe interpretation without changing trades.
    benchmark_symbol: str = "SPY"

    # float in [0, 1]. Higher floors demand stronger within-sector rank and can
    # improve factor purity / Sharpe, but shrink LastUniverseRankedCount and capacity.
    sector_percentile_min: float = 0.70

    # float weights that should sum to 1.0. Higher ROE weight increases exposure
    # to capital-efficient firms and can improve Profit-Loss Ratio / Alpha if that
    # factor is working; overweighting any single factor raises regime concentration risk.
    roe_weight: float = 0.3

    # float in [0, 1]. Higher revenue-growth weight increases momentum/growth tilt,
    # often improving Return in expansion regimes but raising drawdown in rotations.
    revenue_growth_weight: float = 0.3

    # float in [0, 1]. Higher earnings-growth weight makes the basket more sensitive
    # to earnings acceleration, potentially lifting Win Rate but increasing cyclicality.
    net_income_growth_weight: float = 0.2

    # float in [0, 1]. Higher inverse-PEG weight adds valuation discipline, which
    # can improve Drawdown / Sortino, but may miss expensive momentum leaders.
    inverse_peg_weight: float = 0.2

    # float in [0, 1]. Higher fundamental-component weight reduces timing influence
    # and can stabilize Turnover / Fees, but may weaken tactical entry quality.
    fundamental_component_weight: float = 0.7

    # float in [0, 1]. Higher timing-component weight reacts faster to tape
    # conditions, which can improve short-horizon Alpha but increase Fees and noise.
    timing_component_weight: float = 0.3

    # float in [0, 1]. Higher relative-volume weight favors participation spikes,
    # which can improve breakout capture but also increase chase risk.
    timing_relative_volume_weight: float = 0.3

    # float in [0, 1]. Higher contraction weight emphasizes setup quality and can
    # improve Drawdown / Sortino, but may lower signal frequency.
    timing_volatility_contraction_weight: float = 0.4

    # float in [0, 1]. Higher trend weight increases trend-following exposure,
    # which can improve CAGR in persistent trends but lag reversals.
    timing_trend_weight: float = 0.3


@dataclass(frozen=True)
class SystemOperationsSettings:
    """Operational controls that still affect the mathematical backtest output."""

    # str. Used in rebalance keys, audit labels, and cloud project identity.
    algorithm_name: str = "QualityGrowthPi"

    # ISO date string YYYY-MM-DD. Earlier start dates increase total trades,
    # fees, drawdown cycles, and the stability of CAGR / Sharpe estimates.
    backtest_start_date: str = "2018-01-01"

    # float > 0. Directly drives Start Equity, End Equity, capacity scaling, and
    # fee/dollar exposure. Percent returns stay comparable; dollar PnL does not.
    initial_cash: float = 100_000.0

    # int >= long_sma. Higher bootstrap depth reduces pending-price / missing-feature
    # skips early in the test, which can change Total Orders and initial equity curve shape.
    bootstrap_history_days: int = 105

    # int >= 0 minutes. Higher freshness tolerance reduces skipped rebalances and
    # therefore raises Total Orders / exposure; lower tolerance protects against stale inputs.
    stale_data_max_age_minutes: int = 30

    # bool. Logging itself does not change math, but disabling it shortens the
    # operator feedback loop by reducing noise when iterating on cloud runs.
    cloud_audit_logging: bool = True


@dataclass(frozen=True)
class StrategySettings:
    """Unified strategy settings grouped by the causal area they influence."""

    profitability: ProfitabilitySettings = field(default_factory=ProfitabilitySettings)
    trade_mechanics: TradeMechanicsSettings = field(default_factory=TradeMechanicsSettings)
    risk_volatility: RiskVolatilitySettings = field(default_factory=RiskVolatilitySettings)
    quant_scores: QuantScoreSettings = field(default_factory=QuantScoreSettings)
    system_operations: SystemOperationsSettings = field(default_factory=SystemOperationsSettings)

    def to_strategy_payload(self) -> dict[str, Any]:
        """Return the canonical strategy payload consumed by shared scoring/runtime code."""

        return {
            "algorithm_name": self.system_operations.algorithm_name,
            "benchmark_symbol": self.quant_scores.benchmark_symbol,
            "rebalance": {
                "frequency": self.trade_mechanics.frequency,
                "anchor_symbol": self.trade_mechanics.anchor_symbol,
                "after_open_minutes": self.trade_mechanics.after_open_minutes,
                "max_holdings": self.trade_mechanics.max_holdings,
                "candidate_pool_multiplier": self.trade_mechanics.candidate_pool_multiplier,
            },
            "universe": {
                "exchange_id": self.trade_mechanics.exchange_id,
                "min_market_cap": self.trade_mechanics.min_market_cap,
                "min_price": self.trade_mechanics.min_price,
                "require_fundamental_data": self.trade_mechanics.require_fundamental_data,
            },
            "thresholds": {
                "roe_min": self.profitability.roe_min,
                "gross_margin_min": self.profitability.gross_margin_min,
                "debt_to_equity_min": self.risk_volatility.debt_to_equity_min,
                "debt_to_equity_max": self.risk_volatility.debt_to_equity_max,
                "revenue_growth_min": self.profitability.revenue_growth_min,
                "net_income_growth_min": self.profitability.net_income_growth_min,
                "pe_ratio_min": self.profitability.pe_ratio_min,
                "peg_ratio_min": self.profitability.peg_ratio_min,
                "peg_ratio_max": self.profitability.peg_ratio_max,
                "sector_percentile_min": self.quant_scores.sector_percentile_min,
            },
            "weights": {
                "roe": self.quant_scores.roe_weight,
                "revenue_growth": self.quant_scores.revenue_growth_weight,
                "net_income_growth": self.quant_scores.net_income_growth_weight,
                "inverse_peg": self.quant_scores.inverse_peg_weight,
                "fundamental_component": self.quant_scores.fundamental_component_weight,
                "timing_component": self.quant_scores.timing_component_weight,
                "timing_relative_volume": self.quant_scores.timing_relative_volume_weight,
                "timing_volatility_contraction": self.quant_scores.timing_volatility_contraction_weight,
                "timing_trend": self.quant_scores.timing_trend_weight,
            },
            "timing": {
                "volume_window": self.risk_volatility.volume_window,
                "price_window": self.risk_volatility.price_window,
                "short_sma": self.risk_volatility.short_sma,
                "long_sma": self.risk_volatility.long_sma,
                "relative_volume_threshold": self.risk_volatility.relative_volume_threshold,
                "volatility_contraction_threshold": self.risk_volatility.volatility_contraction_threshold,
            },
        }

    def to_runtime_payload(self) -> dict[str, Any]:
        """Return runtime controls that still affect the backtest path."""

        return {
            "backtest_start_date": self.system_operations.backtest_start_date,
            "initial_cash": self.system_operations.initial_cash,
            "bootstrap_history_days": self.system_operations.bootstrap_history_days,
            "stale_data_max_age_minutes": self.system_operations.stale_data_max_age_minutes,
            "fine_universe_limit": self.trade_mechanics.fine_universe_limit,
            "cloud_audit_logging": self.system_operations.cloud_audit_logging,
        }


@dataclass(frozen=True)
class StatArbUniverseSettings:
    """Universe and history controls for daily stat-arb research."""

    # list[str]. The stat-arb path currently uses a curated liquid universe to
    # keep clustering stable and paper execution realistic. Expanding the list
    # increases opportunity count, but also raises turnover, overlap risk, and
    # cloud backtest runtime.
    symbols: tuple[str, ...] = (
        "AAPL",
        "MSFT",
        "NVDA",
        "AVGO",
        "AMD",
        "QCOM",
        "META",
        "GOOGL",
        "AMZN",
        "TSM",
        "ADBE",
        "CRM",
    )

    # int > 0. Longer history windows stabilize correlation graphs and reduce
    # cluster churn, but slow adaptation when relationships break.
    lookback_days: int = 90

    # int > 0 and <= lookback_days. Higher minimum history improves pair-feature
    # integrity and reduces false signals, but shrinks the usable universe.
    min_history_days: int = 60

    # float > 0. Higher price floors avoid noisy small-ticket names and improve
    # borrow/fill realism, but reduce the candidate universe.
    min_price: float = 5.0


@dataclass(frozen=True)
class StatArbGraphSettings:
    """Return-graph construction parameters."""

    # int > 0. Shorter correlation lookbacks respond faster to regime shifts but
    # produce noisier clusters and more unstable turnover.
    correlation_lookback_days: int = 60

    # float in (0, 1]. Higher minimum correlation improves pair coherence and
    # can lift Win Rate / Profit-Loss Ratio, but reduces cluster breadth.
    min_correlation: float = 0.65

    # int >= 2. Higher cluster-size floors reduce single-edge noise, but can
    # eliminate sparse sectors during stressed regimes.
    min_cluster_size: int = 2

    # int >= min_cluster_size. Lower caps reduce concentration and overlap risk,
    # but may miss richer cluster structures.
    max_cluster_size: int = 6

    # int >= 1. More pairs per cluster increase Total Orders and fee drag, while
    # fewer pairs improve selectivity and capacity discipline.
    max_pairs_per_cluster: int = 2


@dataclass(frozen=True)
class StatArbSpreadSettings:
    """Signal and spread thresholds for pair entry."""

    # int > 0. Longer z-score windows stabilize mean-reversion estimates and can
    # improve Sharpe, but delay new entries.
    zscore_lookback_days: int = 30

    # float > 0. Higher entry thresholds reduce trade count and fees, but may
    # miss profitable smaller dislocations.
    entry_z_score: float = 1.75

    # float >= 0. Higher take-profit thresholds close trades earlier, increasing
    # Win Rate but possibly truncating average win size.
    take_profit_z_score: float = 0.35

    # float > entry_z_score. Lower stop-loss thresholds reduce drawdown tails,
    # but also raise the Loss Rate by cutting trades sooner.
    stop_loss_z_score: float = 3.25

    # float > 0. Lower maximum half-life filters to faster mean-reverting pairs,
    # often improving capital efficiency but shrinking opportunity count.
    max_half_life_days: float = 20.0

    # float in [0, 1]. Higher stability floors reduce regime-break risk but
    # reject more pairs in volatile markets.
    min_correlation_stability: float = 0.45

    # float >= 0. Higher edge floors explicitly compensate for fees/slippage and
    # improve net profitability, but can sharply reduce Total Orders.
    min_expected_edge_bps: float = 18.0

    # float >= 0. Higher modeled costs make the filter more conservative and are
    # directly linked to Net Profit after fees and turnover sensitivity.
    transaction_cost_bps: float = 5.0


@dataclass(frozen=True)
class StatArbExitSettings:
    """Dynamic risk-management controls for open pair trades."""

    # float >= minimum_take_profit_z_score. Higher initial take-profit values
    # monetize spread convergence sooner and can improve Win Rate.
    initial_take_profit_z_score: float = 0.35
    minimum_take_profit_z_score: float = 0.10

    # float >= minimum_stop_loss_z_score. Lower initial stop-loss values reduce
    # Drawdown but can increase whipsaw losses.
    initial_stop_loss_z_score: float = 3.25
    minimum_stop_loss_z_score: float = 2.10

    # float > 0. Shorter half-lives tighten exits faster, reducing tail risk but
    # increasing the chance of premature exits.
    decay_half_life_days: float = 8.0

    # int > 0. Lower maximum holding periods reduce stale capital usage and
    # sudden breakdown risk, but may cut late-converging winners.
    max_holding_days: int = 15


@dataclass(frozen=True)
class StatArbSizingSettings:
    """Kelly-based sizing and portfolio-neutrality caps."""

    # float > 0. Higher payoff floors make Kelly sizing more conservative and
    # reduce leverage when expected asymmetry is weak.
    payoff_ratio_floor: float = 1.0

    # float in (0, 1). Higher probability floors reduce trade count and fee
    # drag, but can lower Return if the ML filter is too selective.
    probability_floor: float = 0.52

    # float in (0, 1]. Higher minimum fractions raise capital usage per trade,
    # which can improve Return but worsen Drawdown on weak signals.
    min_fraction: float = 0.01
    max_fraction: float = 0.12

    # float in (0, 1+). Tighter per-trade gross caps reduce single-pair blow-up
    # risk and improve capacity realism.
    max_gross_exposure_per_trade: float = 0.18
    max_gross_exposure_total: float = 1.25
    max_net_exposure_total: float = 0.15

    # int >= 1. Lower open-pair caps reduce overlap and fee drag, but also
    # reduce diversification across clusters.
    max_open_pairs: int = 6
    max_pairs_per_cluster: int = 2

    # float in [0, 1]. Higher penalties shrink sizes when symbols or clusters
    # overlap, directly reducing concentration risk.
    overlap_penalty: float = 0.5


@dataclass(frozen=True)
class StatArbMLMemberSettings:
    """One fixed inference member from the offline-trained ensemble."""

    name: str
    intercept: float
    weights: dict[str, float]


@dataclass(frozen=True)
class StatArbMLSettings:
    """Inference-only ML filter settings."""

    # str enum: embedded_scorecard or object_store_model. Object-store mode
    # enables the trained ensemble as the primary filter; embedded_scorecard is
    # kept as the resilient fallback path for backtests and live runs.
    mode: str = "embedded_scorecard"

    # str. Model version is persisted for regression and audit attribution.
    model_version: str = "ensemble_v1"

    # float in (0, 1). Higher thresholds reduce Total Orders and Fees, and
    # should improve net expectancy if the model is calibrated.
    probability_threshold: float = 0.58

    # float in (0, 1). Higher minimum confidence reduces ambiguous trades and
    # can improve Sortino / Information Ratio at the expense of opportunity count.
    min_confidence: float = 0.55

    # str. Versioned QuantConnect Object Store key for the trained model
    # artifact. Pinning a specific key makes backtests reproducible.
    object_store_model_key: str = ""

    # str filesystem path. Used by non-cloud workflows to validate or load the
    # same joblib artifact locally before it is uploaded to QuantConnect.
    local_model_path: str = "/mnt/nvme_data/shared/quant_gpt/data/models/stat_arb/ensemble.joblib"

    # str. Feature schema version must match the training artifact exactly to
    # prevent silent feature-order drift between Ubuntu training and inference.
    feature_schema_version: str = "stat_arb_v1"

    # str enum. Fixed to embedded_scorecard so missing/broken artifacts never
    # bypass the ML filter in live or backtest mode.
    fallback_mode: str = "embedded_scorecard"

    members: tuple[StatArbMLMemberSettings, ...] = (
        StatArbMLMemberSettings(
            name="mean_reversion_core",
            intercept=-0.15,
            weights={
                "abs_z_score": 0.55,
                "mean_reversion_speed": 0.90,
                "correlation_stability": 0.80,
                "expected_edge_bps_norm": 0.65,
                "transaction_cost_penalty": -0.60,
            },
        ),
        StatArbMLMemberSettings(
            name="fee_sensitivity",
            intercept=-0.10,
            weights={
                "abs_z_score": 0.35,
                "half_life_score": 0.75,
                "expected_edge_bps_norm": 0.80,
                "transaction_cost_penalty": -0.85,
            },
        ),
        StatArbMLMemberSettings(
            name="cluster_stability",
            intercept=-0.05,
            weights={
                "correlation": 0.60,
                "correlation_stability": 0.95,
                "half_life_score": 0.45,
                "transaction_cost_penalty": -0.30,
            },
        ),
        StatArbMLMemberSettings(
            name="extreme_move_guard",
            intercept=-0.20,
            weights={
                "abs_z_score": 0.95,
                "mean_reversion_speed": 0.55,
                "half_life_score": 0.40,
                "transaction_cost_penalty": -0.50,
            },
        ),
        StatArbMLMemberSettings(
            name="balanced_vote",
            intercept=-0.12,
            weights={
                "abs_z_score": 0.50,
                "correlation": 0.35,
                "correlation_stability": 0.55,
                "expected_edge_bps_norm": 0.55,
                "half_life_score": 0.35,
                "transaction_cost_penalty": -0.45,
            },
        ),
    )


@dataclass(frozen=True)
class StatArbSystemOperationsSettings:
    """Operational parameters that still move the stat-arb backtest output."""

    algorithm_name: str = "GraphStatArb"
    backtest_start_date: str = "2022-01-01"
    initial_cash: float = 100_000.0
    bootstrap_history_days: int = 120
    stale_data_max_age_minutes: int = 30
    cloud_audit_logging: bool = True


@dataclass(frozen=True)
class StatArbStrategySettings:
    """Single-source stat-arb settings used by shared code and LEAN sync."""

    universe: StatArbUniverseSettings = field(default_factory=StatArbUniverseSettings)
    graph: StatArbGraphSettings = field(default_factory=StatArbGraphSettings)
    spread: StatArbSpreadSettings = field(default_factory=StatArbSpreadSettings)
    exit_policy: StatArbExitSettings = field(default_factory=StatArbExitSettings)
    sizing: StatArbSizingSettings = field(default_factory=StatArbSizingSettings)
    ml_filter: StatArbMLSettings = field(default_factory=StatArbMLSettings)
    system_operations: StatArbSystemOperationsSettings = field(default_factory=StatArbSystemOperationsSettings)

    def to_strategy_payload(self) -> dict[str, Any]:
        """Return the canonical stat-arb payload."""

        return {
            "algorithm_name": self.system_operations.algorithm_name,
            "benchmark_symbol": "SPY",
            "universe": {
                "symbols": list(self.universe.symbols),
                "lookback_days": self.universe.lookback_days,
                "min_history_days": self.universe.min_history_days,
                "min_price": self.universe.min_price,
            },
            "graph": {
                "correlation_lookback_days": self.graph.correlation_lookback_days,
                "min_correlation": self.graph.min_correlation,
                "min_cluster_size": self.graph.min_cluster_size,
                "max_cluster_size": self.graph.max_cluster_size,
                "max_pairs_per_cluster": self.graph.max_pairs_per_cluster,
            },
            "spread": {
                "zscore_lookback_days": self.spread.zscore_lookback_days,
                "entry_z_score": self.spread.entry_z_score,
                "take_profit_z_score": self.spread.take_profit_z_score,
                "stop_loss_z_score": self.spread.stop_loss_z_score,
                "max_half_life_days": self.spread.max_half_life_days,
                "min_correlation_stability": self.spread.min_correlation_stability,
                "min_expected_edge_bps": self.spread.min_expected_edge_bps,
                "transaction_cost_bps": self.spread.transaction_cost_bps,
            },
            "exit_policy": {
                "initial_take_profit_z_score": self.exit_policy.initial_take_profit_z_score,
                "minimum_take_profit_z_score": self.exit_policy.minimum_take_profit_z_score,
                "initial_stop_loss_z_score": self.exit_policy.initial_stop_loss_z_score,
                "minimum_stop_loss_z_score": self.exit_policy.minimum_stop_loss_z_score,
                "decay_half_life_days": self.exit_policy.decay_half_life_days,
                "max_holding_days": self.exit_policy.max_holding_days,
            },
            "sizing": {
                "payoff_ratio_floor": self.sizing.payoff_ratio_floor,
                "probability_floor": self.sizing.probability_floor,
                "min_fraction": self.sizing.min_fraction,
                "max_fraction": self.sizing.max_fraction,
                "max_gross_exposure_per_trade": self.sizing.max_gross_exposure_per_trade,
                "max_gross_exposure_total": self.sizing.max_gross_exposure_total,
                "max_net_exposure_total": self.sizing.max_net_exposure_total,
                "max_open_pairs": self.sizing.max_open_pairs,
                "max_pairs_per_cluster": self.sizing.max_pairs_per_cluster,
                "overlap_penalty": self.sizing.overlap_penalty,
            },
            "ml_filter": {
                "mode": self.ml_filter.mode,
                "model_version": self.ml_filter.model_version,
                "probability_threshold": self.ml_filter.probability_threshold,
                "min_confidence": self.ml_filter.min_confidence,
                "object_store_model_key": self.ml_filter.object_store_model_key,
                "local_model_path": self.ml_filter.local_model_path,
                "feature_schema_version": self.ml_filter.feature_schema_version,
                "fallback_mode": self.ml_filter.fallback_mode,
                "members": [
                    {
                        "name": member.name,
                        "intercept": member.intercept,
                        "weights": dict(member.weights),
                    }
                    for member in self.ml_filter.members
                ],
            },
        }

    def to_runtime_payload(self) -> dict[str, Any]:
        """Return runtime controls shared with backtest/live wrappers."""

        return {
            "backtest_start_date": self.system_operations.backtest_start_date,
            "initial_cash": self.system_operations.initial_cash,
            "bootstrap_history_days": self.system_operations.bootstrap_history_days,
            "stale_data_max_age_minutes": self.system_operations.stale_data_max_age_minutes,
            "fine_universe_limit": len(self.universe.symbols),
            "cloud_audit_logging": self.system_operations.cloud_audit_logging,
        }


DEFAULT_STRATEGY_SETTINGS = StrategySettings()
SHORT_REGRESSION_SETTINGS = replace(
    DEFAULT_STRATEGY_SETTINGS,
    system_operations=replace(
        DEFAULT_STRATEGY_SETTINGS.system_operations,
        backtest_start_date="2025-01-01",
    ),
)

DEFAULT_STAT_ARB_SETTINGS = StatArbStrategySettings()
SHORT_REGRESSION_STAT_ARB_SETTINGS = replace(
    DEFAULT_STAT_ARB_SETTINGS,
    system_operations=replace(
        DEFAULT_STAT_ARB_SETTINGS.system_operations,
        backtest_start_date="2025-01-01",
    ),
)

QUALITY_GROWTH_PROFILES: dict[str, StrategySettings] = {
    "default": DEFAULT_STRATEGY_SETTINGS,
    "short_regression": SHORT_REGRESSION_SETTINGS,
}

STAT_ARB_PROFILES: dict[str, StatArbStrategySettings] = {
    "default": DEFAULT_STAT_ARB_SETTINGS,
    "short_regression": SHORT_REGRESSION_STAT_ARB_SETTINGS,
}


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _apply_stat_arb_env_overrides(settings: StatArbStrategySettings) -> StatArbStrategySettings:
    """Overlay runtime-selectable stat-arb ML settings without scattering config."""

    ml_filter = replace(
        settings.ml_filter,
        mode=_env_or_default("STAT_ARB_ML_FILTER_MODE", settings.ml_filter.mode),
        model_version=_env_or_default("STAT_ARB_ML_MODEL_VERSION", settings.ml_filter.model_version),
        object_store_model_key=_env_or_default(
            "STAT_ARB_OBJECT_STORE_MODEL_KEY",
            settings.ml_filter.object_store_model_key,
        ),
        local_model_path=_env_or_default("STAT_ARB_LOCAL_MODEL_PATH", settings.ml_filter.local_model_path),
        feature_schema_version=_env_or_default(
            "STAT_ARB_FEATURE_SCHEMA_VERSION",
            settings.ml_filter.feature_schema_version,
        ),
        fallback_mode=_env_or_default("STAT_ARB_ML_FALLBACK_MODE", settings.ml_filter.fallback_mode),
    )
    return replace(settings, ml_filter=ml_filter)


def load_strategy_settings(profile: str | None = None) -> StrategySettings:
    """Return the selected quality-growth profile."""

    selected_profile = (profile or os.getenv("QUANT_GPT_SETTINGS_PROFILE", "default")).strip().lower()
    try:
        return QUALITY_GROWTH_PROFILES[selected_profile]
    except KeyError as exc:  # pragma: no cover - defensive branch
        available = ", ".join(sorted(QUALITY_GROWTH_PROFILES))
        raise ValueError(f"Unknown strategy settings profile '{selected_profile}'. Available: {available}") from exc


def load_stat_arb_settings(profile: str | None = None) -> StatArbStrategySettings:
    """Return the selected stat-arb profile."""

    selected_profile = (profile or os.getenv("QUANT_GPT_SETTINGS_PROFILE", "default")).strip().lower()
    try:
        return _apply_stat_arb_env_overrides(STAT_ARB_PROFILES[selected_profile])
    except KeyError as exc:  # pragma: no cover - defensive branch
        available = ", ".join(sorted(STAT_ARB_PROFILES))
        raise ValueError(f"Unknown stat-arb settings profile '{selected_profile}'. Available: {available}") from exc


def build_quality_growth_payload(profile: str | None = None) -> dict[str, Any]:
    """Return the canonical quality-growth payload."""

    return load_strategy_settings(profile).to_strategy_payload()


def build_stat_arb_payload(profile: str | None = None) -> dict[str, Any]:
    """Return the canonical stat-arb payload."""

    return load_stat_arb_settings(profile).to_strategy_payload()


def build_strategy_payload(profile: str | None = None, strategy_mode: str | None = None) -> dict[str, Any]:
    """Return the canonical payload for the selected strategy family."""

    mode = (strategy_mode or os.getenv("QUANT_GPT_STRATEGY_MODE", "quality_growth")).strip().lower()
    if mode == "stat_arb_graph_pairs":
        return build_stat_arb_payload(profile)
    return build_quality_growth_payload(profile)


def build_runtime_payload(profile: str | None = None, strategy_mode: str | None = None) -> dict[str, Any]:
    """Return runtime controls for the selected strategy family."""

    mode = (strategy_mode or os.getenv("QUANT_GPT_STRATEGY_MODE", "quality_growth")).strip().lower()
    if mode == "stat_arb_graph_pairs":
        return load_stat_arb_settings(profile).to_runtime_payload()
    return load_strategy_settings(profile).to_runtime_payload()


def default_lean_project_name(strategy_mode: str | None = None) -> str:
    """Map the strategy family to its default LEAN project directory."""

    mode = (strategy_mode or os.getenv("QUANT_GPT_STRATEGY_MODE", "quality_growth")).strip().lower()
    if mode == "stat_arb_graph_pairs":
        return "GraphStatArb"
    return "QualityGrowthPi"
