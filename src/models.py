"""Typed models for strategy, advisory, and runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @model_validator(mode="after")
    def validate_bounds(self) -> "FundamentalThresholds":
        if self.debt_to_equity_max <= self.debt_to_equity_min:
            raise ValueError("debt_to_equity_max must exceed debt_to_equity_min")
        if self.peg_ratio_max <= self.peg_ratio_min:
            raise ValueError("peg_ratio_max must exceed peg_ratio_min")
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

    frequency: str = "monthly"
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
    stale_data_max_age_minutes: int = 30
    bootstrap_history_days: int = 35


class LLMPolicyConfig(BaseConfigModel):
    """Deterministic caps applied to advisory outputs."""

    low_confidence_threshold: float = 0.55
    low_coverage_threshold: float = 0.4
    max_weight_reduction: float = 0.5
    require_manual_review_on_reduce_size: bool = True


class LLMPromptConfig(BaseConfigModel):
    """Prompt filenames for the advisory system."""

    sentiment: str = "sentiment_system.txt"
    narrative: str = "narrative_system.txt"
    advisory: str = "advisory_system.txt"
    schema: str = "extraction_schema.json"


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


class AdvisoryEnvelope(BaseModel):
    """Advisory payload plus policy decision for persistence."""

    model_config = ConfigDict(extra="forbid")

    advisory: LLMAdvisoryOutput
    decision: RiskDecision
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
