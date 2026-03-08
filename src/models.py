"""Typed models for strategy, advisory, and runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class ProviderMode(str, Enum):
    """Supported provider modes."""

    QUANTCONNECT_LOCAL = "quantconnect_local"
    EXTERNAL_EQUIVALENT = "external_equivalent"
    PAPER_TRADING = "paper_trading"
    LLM_ADVISORY = "llm_advisory"


class LLMMode(str, Enum):
    """LLM policy modes."""

    DISABLED = "disabled"
    OBSERVE_ONLY = "observe_only"
    ADVISORY_ONLY = "advisory_only"
    RISK_MODIFIER = "risk_modifier"


class BacktestMode(str, Enum):
    """Supported backtest execution modes."""

    CLOUD = "cloud"
    LOCAL = "local"


class DeploymentTarget(str, Enum):
    """Where LEAN live/paper deployments execute."""

    CLOUD = "cloud"
    LOCAL = "local"


class ExecutionBroker(str, Enum):
    """Supported execution brokers for staged deployment."""

    ALPACA = "alpaca"
    IBKR = "ibkr"
    QUANTCONNECT_PAPER = "quantconnect_paper"


class StrategyMode(str, Enum):
    """Supported strategy families."""

    QUALITY_GROWTH = "quality_growth"
    STAT_ARB_GRAPH_PAIRS = "stat_arb_graph_pairs"


class MLFilterMode(str, Enum):
    """Supported stat-arb ML inference backends."""

    EMBEDDED_SCORECARD = "embedded_scorecard"
    OBJECT_STORE_MODEL = "object_store_model"


class NewsProviderMode(str, Enum):
    """Supported news ingestion modes."""

    FILE = "file"
    MASSIVE = "massive"
    ALPHA_VANTAGE = "alpha_vantage"
    COMPOSITE = "composite"


class SentimentLabel(str, Enum):
    """Normalized sentiment labels."""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    UNKNOWN = "unknown"


class EventUrgency(str, Enum):
    """Urgency levels derived from news flow."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class SuggestedAction(str, Enum):
    """Actions an advisory payload may suggest."""

    NO_EFFECT = "no_effect"
    CAUTION = "caution"
    MANUAL_REVIEW = "manual_review"
    REDUCE_SIZE = "reduce_size"


class BaseConfigModel(BaseModel):
    """Base model that forbids unknown fields for deterministic config loading."""

    model_config = ConfigDict(extra="forbid")


class FundamentalThresholds(BaseConfigModel):
    """Screening thresholds for the fundamental universe."""

    roe_min: float = 0.15
    gross_margin_min: float = 0.30
    debt_to_equity_min: float = 0.0
    debt_to_equity_max: float = 2.0
    revenue_growth_min: float = 0.10
    net_income_growth_min: float = 0.10
    pe_ratio_min: float = 0.0
    peg_ratio_min: float = 0.0
    peg_ratio_max: float = 2.0
    sector_percentile_min: float = 0.7

    @model_validator(mode="after")
    def validate_bounds(self) -> "FundamentalThresholds":
        if self.debt_to_equity_max <= self.debt_to_equity_min:
            raise ValueError("debt_to_equity_max must exceed debt_to_equity_min")
        if self.peg_ratio_max <= self.peg_ratio_min:
            raise ValueError("peg_ratio_max must exceed peg_ratio_min")
        if not 0.0 <= self.sector_percentile_min <= 1.0:
            raise ValueError("sector_percentile_min must be between 0.0 and 1.0")
        return self


class StrategyWeights(BaseConfigModel):
    """Weights for ranking and combined scoring."""

    roe: float = 0.3
    revenue_growth: float = 0.3
    net_income_growth: float = 0.2
    inverse_peg: float = 0.2
    fundamental_component: float = 0.6
    timing_component: float = 0.4
    timing_relative_volume: float = 0.3
    timing_volatility_contraction: float = 0.4
    timing_trend: float = 0.3

    @model_validator(mode="after")
    def validate_sums(self) -> "StrategyWeights":
        if round(self.roe + self.revenue_growth + self.net_income_growth + self.inverse_peg, 6) != 1:
            raise ValueError("fundamental sub-weights must sum to 1.0")
        if round(self.fundamental_component + self.timing_component, 6) != 1:
            raise ValueError("component weights must sum to 1.0")
        if (
            round(
                self.timing_relative_volume
                + self.timing_volatility_contraction
                + self.timing_trend,
                6,
            )
            != 1
        ):
            raise ValueError("timing sub-weights must sum to 1.0")
        return self


class RebalanceConfig(BaseConfigModel):
    """Portfolio construction and rebalance cadence settings."""

    frequency: str = "daily"
    anchor_symbol: str = "SPY"
    after_open_minutes: int = 30
    max_holdings: int = 20
    candidate_pool_multiplier: int = 3

    @field_validator("max_holdings", "candidate_pool_multiplier")
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value


class UniverseConfig(BaseConfigModel):
    """Static filters for the fundamental universe."""

    exchange_id: str = "NYS"
    min_market_cap: float = 1_000_000_000
    min_price: float = 5.0
    require_fundamental_data: bool = True


class TimingConfig(BaseConfigModel):
    """Indicator windows and thresholds for timing overlays."""

    volume_window: int = 20
    price_window: int = 20
    short_sma: int = 10
    long_sma: int = 30
    relative_volume_threshold: float = 1.2
    volatility_contraction_threshold: float = 0.85

    @model_validator(mode="after")
    def validate_windows(self) -> "TimingConfig":
        if self.short_sma >= self.long_sma:
            raise ValueError("short_sma must be less than long_sma")
        if self.price_window < 4:
            raise ValueError("price_window must be at least 4")
        return self


class StrategyParameters(BaseConfigModel):
    """Complete strategy configuration."""

    algorithm_name: str = "QualityGrowthPi"
    benchmark_symbol: str = "SPY"
    rebalance: RebalanceConfig = Field(default_factory=RebalanceConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    thresholds: FundamentalThresholds = Field(default_factory=FundamentalThresholds)
    weights: StrategyWeights = Field(default_factory=StrategyWeights)
    timing: TimingConfig = Field(default_factory=TimingConfig)


class RuntimeConfig(BaseConfigModel):
    """Runtime controls loaded from app config and environment."""

    environment: str = "dev"
    strategy_mode: StrategyMode = StrategyMode.QUALITY_GROWTH
    provider_mode: ProviderMode = ProviderMode.QUANTCONNECT_LOCAL
    llm_enabled: bool = True
    llm_mode: LLMMode = LLMMode.OBSERVE_ONLY
    timezone: str = "America/New_York"
    state_db: str = "state/quant_gpt.db"
    runtime_lock: str = "state/runtime.lock"
    heartbeat_seconds: int = 60


class PathConfig(BaseConfigModel):
    """Repository-relative path settings."""

    logs_dir: str = "logs"
    state_dir: str = "state"
    results_dir: str = "results"
    data_dir: str = "data"
    prompts_dir: str = "config/prompts"


class ExecutionConfig(BaseConfigModel):
    """Runtime execution safety settings."""

    paper_default: bool = True
    require_live_confirmation: bool = True
    backtest_start_date: str = "2018-01-01"
    initial_cash: float = 100_000.0
    stale_data_max_age_minutes: int = 30
    bootstrap_history_days: int = 35
    fine_universe_limit: int = 1000

    @field_validator("initial_cash")
    @classmethod
    def positive_cash(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("initial_cash must be positive")
        return value

    @field_validator("stale_data_max_age_minutes", "bootstrap_history_days", "fine_universe_limit")
    @classmethod
    def positive_execution_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("backtest_start_date")
    @classmethod
    def valid_start_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y-%m-%d")
        return value


class StatArbUniverseConfig(BaseConfigModel):
    """Universe and history controls for the stat-arb research path."""

    symbols: list[str] = Field(
        default_factory=lambda: [
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
        ]
    )
    lookback_days: int = 90
    min_history_days: int = 60
    min_price: float = 5.0

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: list[str]) -> list[str]:
        normalized = sorted({symbol.strip().upper() for symbol in value if symbol.strip()})
        if len(normalized) < 2:
            raise ValueError("stat-arb universe requires at least two symbols")
        return normalized


class StatArbGraphConfig(BaseConfigModel):
    """Graph construction controls for return-correlation clustering."""

    correlation_lookback_days: int = 60
    min_correlation: float = 0.65
    min_cluster_size: int = 2
    max_cluster_size: int = 6
    max_pairs_per_cluster: int = 2

    @model_validator(mode="after")
    def validate_graph(self) -> "StatArbGraphConfig":
        if not 0.0 < self.min_correlation <= 1.0:
            raise ValueError("min_correlation must be between 0.0 and 1.0")
        if self.max_cluster_size < self.min_cluster_size:
            raise ValueError("max_cluster_size must be at least min_cluster_size")
        if self.max_pairs_per_cluster <= 0:
            raise ValueError("max_pairs_per_cluster must be positive")
        return self


class StatArbSpreadConfig(BaseConfigModel):
    """Spread-signal thresholds for pair generation and entry."""

    zscore_lookback_days: int = 30
    entry_z_score: float = 1.75
    take_profit_z_score: float = 0.35
    stop_loss_z_score: float = 3.25
    max_half_life_days: float = 20.0
    min_correlation_stability: float = 0.45
    min_expected_edge_bps: float = 18.0
    transaction_cost_bps: float = 5.0

    @model_validator(mode="after")
    def validate_spread(self) -> "StatArbSpreadConfig":
        if self.entry_z_score <= 0:
            raise ValueError("entry_z_score must be positive")
        if self.take_profit_z_score < 0:
            raise ValueError("take_profit_z_score must be non-negative")
        if self.stop_loss_z_score <= self.entry_z_score:
            raise ValueError("stop_loss_z_score must exceed entry_z_score")
        if self.max_half_life_days <= 0:
            raise ValueError("max_half_life_days must be positive")
        return self


class PairExitPolicy(BaseConfigModel):
    """Dynamic exit policy for an open pair trade."""

    initial_take_profit_z_score: float = 0.35
    minimum_take_profit_z_score: float = 0.10
    initial_stop_loss_z_score: float = 3.25
    minimum_stop_loss_z_score: float = 2.10
    decay_half_life_days: float = 8.0
    max_holding_days: int = 15

    @model_validator(mode="after")
    def validate_policy(self) -> "PairExitPolicy":
        if self.initial_take_profit_z_score < self.minimum_take_profit_z_score:
            raise ValueError("initial_take_profit_z_score must exceed or equal minimum_take_profit_z_score")
        if self.initial_stop_loss_z_score < self.minimum_stop_loss_z_score:
            raise ValueError("initial_stop_loss_z_score must exceed or equal minimum_stop_loss_z_score")
        if self.decay_half_life_days <= 0:
            raise ValueError("decay_half_life_days must be positive")
        if self.max_holding_days <= 0:
            raise ValueError("max_holding_days must be positive")
        return self


class KellySizingPolicy(BaseConfigModel):
    """Sizing caps for pair trades."""

    payoff_ratio_floor: float = 1.0
    probability_floor: float = 0.52
    min_fraction: float = 0.01
    max_fraction: float = 0.12
    max_gross_exposure_per_trade: float = 0.18
    max_gross_exposure_total: float = 1.25
    max_net_exposure_total: float = 0.15
    max_open_pairs: int = 6
    max_pairs_per_cluster: int = 2
    overlap_penalty: float = 0.5

    @model_validator(mode="after")
    def validate_policy(self) -> "KellySizingPolicy":
        if self.payoff_ratio_floor <= 0:
            raise ValueError("payoff_ratio_floor must be positive")
        if not 0 < self.probability_floor < 1:
            raise ValueError("probability_floor must be between 0 and 1")
        if not 0 < self.min_fraction <= self.max_fraction:
            raise ValueError("min_fraction must be positive and <= max_fraction")
        if self.max_open_pairs <= 0:
            raise ValueError("max_open_pairs must be positive")
        if self.max_pairs_per_cluster <= 0:
            raise ValueError("max_pairs_per_cluster must be positive")
        return self


class MLEnsembleMember(BaseConfigModel):
    """Single offline-trained scorecard used inside the ensemble."""

    name: str
    intercept: float = 0.0
    weights: dict[str, float] = Field(default_factory=dict)


class MLFilterConfig(BaseConfigModel):
    """Inference-only ML filter configuration."""

    mode: MLFilterMode = MLFilterMode.EMBEDDED_SCORECARD
    model_version: str = "softvote_v2026_03_08"
    probability_threshold: float = 0.58
    min_confidence: float = 0.55
    object_store_model_key: str = "28761844/stat-arb/models/softvote_v2026_03_08/ensemble.joblib"
    local_model_path: str = ""
    feature_schema_version: str = "stat_arb_v1"
    fallback_mode: MLFilterMode = MLFilterMode.EMBEDDED_SCORECARD
    members: list[MLEnsembleMember] = Field(default_factory=list)

    @field_validator("object_store_model_key", "local_model_path", "feature_schema_version", "model_version")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_config(self) -> "MLFilterConfig":
        if not self.members:
            raise ValueError("ML filter requires at least one ensemble member")
        if not 0 < self.probability_threshold < 1:
            raise ValueError("probability_threshold must be between 0 and 1")
        if not 0 < self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.fallback_mode != MLFilterMode.EMBEDDED_SCORECARD:
            raise ValueError("fallback_mode must remain embedded_scorecard")
        if self.mode == MLFilterMode.OBJECT_STORE_MODEL and not (
            self.object_store_model_key or self.local_model_path
        ):
            raise ValueError("object_store_model mode requires object_store_model_key or local_model_path")
        if not self.feature_schema_version:
            raise ValueError("feature_schema_version must not be empty")
        return self


class StatArbSettings(BaseConfigModel):
    """Graph-clustered statistical arbitrage strategy configuration."""

    algorithm_name: str = "GraphStatArb"
    benchmark_symbol: str = "SPY"
    universe: StatArbUniverseConfig = Field(default_factory=StatArbUniverseConfig)
    graph: StatArbGraphConfig = Field(default_factory=StatArbGraphConfig)
    spread: StatArbSpreadConfig = Field(default_factory=StatArbSpreadConfig)
    exit_policy: PairExitPolicy = Field(default_factory=PairExitPolicy)
    sizing: KellySizingPolicy = Field(default_factory=KellySizingPolicy)
    ml_filter: MLFilterConfig


class BacktestConfig(BaseConfigModel):
    """Backtest deployment configuration."""

    mode: BacktestMode = BacktestMode.CLOUD
    project_name: str = "QualityGrowthPi"
    push_on_cloud: bool = True
    open_results: bool = False


class PaperTradingConfig(BaseConfigModel):
    """Paper-trading deployment configuration."""

    deployment_target: DeploymentTarget = DeploymentTarget.CLOUD
    broker: ExecutionBroker = ExecutionBroker.ALPACA
    environment: str = "paper"
    live_data_provider: str = "QuantConnect"
    historical_data_provider: str = "QuantConnect"
    push_to_cloud: bool = True
    open_results: bool = False

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paper", "live"}:
            raise ValueError("paper trading environment must be 'paper' or 'live'")
        return normalized

    @field_validator("live_data_provider", "historical_data_provider")
    @classmethod
    def non_empty_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider name must not be empty")
        return normalized


class LocalDataStackConfig(BaseConfigModel):
    """Preferred local provider stack for the external-equivalent path."""

    fundamentals_provider: str = "massive_sec_alpha_vantage"
    daily_bars_provider: str = "alpaca"
    news_provider: NewsProviderMode = NewsProviderMode.COMPOSITE

    @field_validator("fundamentals_provider", "daily_bars_provider")
    @classmethod
    def normalize_stack_value(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("stack provider value must not be empty")
        return normalized


class LLMPolicyConfig(BaseConfigModel):
    """Deterministic caps applied to advisory outputs."""

    low_confidence_threshold: float = 0.55
    low_coverage_threshold: float = 0.4
    max_weight_reduction: float = 0.5
    require_manual_review_on_reduce_size: bool = True
    confidence_half_life_hours: float = 24.0

    @field_validator("confidence_half_life_hours")
    @classmethod
    def validate_half_life(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("confidence_half_life_hours must be positive")
        return value


class LLMPromptConfig(BaseConfigModel):
    """Prompt filenames for the advisory system."""

    sentiment: str = "sentiment_system.txt"
    narrative: str = "narrative_system.txt"
    advisory: str = "advisory_system.txt"
    extraction_schema: str = Field(
        default="extraction_schema.json",
        validation_alias=AliasChoices("extraction_schema", "schema"),
    )


class LLMSettingsModel(BaseConfigModel):
    """LLM provider configuration."""

    enabled: bool = True
    provider: str = "gemini"
    default_model: str = "gemini-3.1-flash-lite-preview"
    fallback_model: str = "gemini-3.1-flash"
    timeout_seconds: int = 12
    max_retries: int = 2
    cache_ttl_minutes: int = 240
    max_symbols_per_batch: int = 20
    budget_usd_daily: float = 5.0
    estimated_request_cost_usd: float = 0.001
    mode: LLMMode = LLMMode.OBSERVE_ONLY
    retention_days: int = 30
    prompts: LLMPromptConfig = Field(default_factory=LLMPromptConfig)
    policy: LLMPolicyConfig = Field(default_factory=LLMPolicyConfig)


class FundamentalSnapshot(BaseModel):
    """Point-in-time fundamental values used for ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    as_of: datetime | None = None
    sector_code: str | None = None
    has_fundamental_data: bool = True
    market_cap: float
    exchange_id: str
    price: float
    volume: float
    roe: float | None = None
    gross_margin: float | None = None
    debt_to_equity: float | None = None
    revenue_growth: float | None = None
    net_income_growth: float | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None


class TimingFeatures(BaseModel):
    """Per-symbol timing metrics derived from daily bars."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    relative_volume: float = 0.0
    volatility_ratio: float = 1.0
    short_sma: float = 0.0
    long_sma: float = 0.0
    trend_up: bool = False
    volatility_contraction: bool = False
    timing_score: float = 0.0
    last_updated: datetime | None = None


class RankedCandidate(BaseModel):
    """A symbol ranked by fundamental and timing metrics."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    fundamental_score: float
    timing_score: float = 0.0
    combined_score: float = 0.0
    target_weight: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class RebalanceIntent(BaseModel):
    """The deterministic output of a rebalance cycle."""

    model_config = ConfigDict(extra="forbid")

    rebalance_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    selected_symbols: list[str]
    target_weights: dict[str, float]
    scored_candidates: list[RankedCandidate]
    llm_policy_mode: LLMMode = LLMMode.OBSERVE_ONLY
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClusterSnapshot(BaseModel):
    """Deterministic snapshot of one return-correlation cluster."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: str
    as_of: datetime
    symbols: list[str]
    average_correlation: float
    edge_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpreadFeatures(BaseModel):
    """Per-pair spread state used for signal generation and ML filtering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str
    cluster_id: str
    first_symbol: str
    second_symbol: str
    hedge_ratio: float
    correlation: float
    correlation_stability: float
    current_spread: float
    spread_mean: float
    spread_std: float
    z_score: float
    mean_reversion_speed: float
    half_life_days: float
    transaction_cost_bps: float
    expected_edge_bps: float
    last_updated: datetime


class PairCandidate(BaseModel):
    """Candidate pair or spread generated from a cluster."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str
    cluster_id: str
    first_symbol: str
    second_symbol: str
    spread_features: SpreadFeatures
    metadata: dict[str, Any] = Field(default_factory=dict)


class MLTradeFilterDecision(BaseModel):
    """Inference result for deciding whether a pair trade should execute."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str
    cluster_id: str
    execute: bool
    predicted_win_probability: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    expected_edge_bps: float
    vote_ratio: float = Field(ge=0.0, le=1.0)
    model_version: str
    rationale: str
    feature_importance: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PairTradeIntent(BaseModel):
    """Pair-native execution target with long and short legs."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str
    cluster_id: str
    long_symbol: str
    short_symbol: str
    long_weight: float
    short_weight: float
    gross_exposure: float
    net_exposure: float
    kelly_fraction: float
    entry_z_score: float
    expected_edge_bps: float
    decision: MLTradeFilterDecision
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PairPositionState(BaseModel):
    """Live or simulated state for an open pair trade."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str
    cluster_id: str
    long_symbol: str
    short_symbol: str
    opened_at: datetime
    status: str = "open"
    entry_z_score: float
    latest_z_score: float
    hedge_ratio: float
    gross_exposure: float
    net_exposure: float
    kelly_fraction: float
    stop_loss_z_score: float
    take_profit_z_score: float
    max_holding_days: int
    notes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HoldingsSnapshot(BaseModel):
    """Persisted holdings state."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "strategy"
    holdings: dict[str, float]


class AuditEvent(BaseModel):
    """Structured audit event persisted to logs and SQLite."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class ProviderPayload(BaseModel):
    """Generic provider fetch payload."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: str
    content_hash: str
    payload: dict[str, Any]


class NewsEvent(BaseModel):
    """Curated text input for the advisory system."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    symbol: str
    headline: str
    body: str
    source: str
    published_at: datetime
    url: str | None = None
    sector: str | None = None
    language: str = "en"


class SentimentSnapshot(BaseModel):
    """Per-symbol sentiment output."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sentiment_score: float
    sentiment_label: SentimentLabel
    confidence_score: float
    source_coverage_score: float
    key_catalysts: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)


class NarrativeSnapshot(BaseModel):
    """Structured narrative tags linked to a symbol or portfolio."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    narrative_tags: list[str] = Field(default_factory=list)
    event_urgency: EventUrgency = EventUrgency.UNKNOWN


class DeterministicDecisionContext(BaseModel):
    """Deterministic scores fed into the LLM prompt."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    fundamental_score: float
    timing_score: float
    combined_score: float
    target_weight: float
    notes: list[str] = Field(default_factory=list)


class LLMAdvisoryOutput(BaseModel):
    """Schema-validated output from the advisory provider."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    sentiment_label: SentimentLabel
    confidence_score: float = Field(ge=0.0, le=1.0)
    key_catalysts: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    narrative_tags: list[str] = Field(default_factory=list)
    event_urgency: EventUrgency = EventUrgency.UNKNOWN
    suggested_action: SuggestedAction = SuggestedAction.NO_EFFECT
    rationale_short: str = Field(min_length=1, max_length=400)
    source_coverage_score: float = Field(ge=0.0, le=1.0)
    model_name: str
    prompt_version: str
    response_hash: str | None = None


class RiskDecision(BaseModel):
    """Deterministic policy outcome from combining strategy and advisory state."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    base_weight: float
    adjusted_weight: float
    action_taken: SuggestedAction = SuggestedAction.NO_EFFECT
    manual_review_required: bool = False
    applied: bool = False
    reason: str = ""
    effective_confidence_score: float | None = None
    decay_factor: float | None = None


class AdvisoryEnvelope(BaseModel):
    """Advisory payload plus policy decision for persistence."""

    model_config = ConfigDict(extra="forbid")

    advisory: LLMAdvisoryOutput
    decision: RiskDecision
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
