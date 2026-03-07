"""Guarded advisory orchestration with schema validation and fail-open behaviour."""

from __future__ import annotations

import hashlib
import json

from src.logging_utils import get_logger
from src.models import (
    AdvisoryEnvelope,
    DeterministicDecisionContext,
    LLMAdvisoryOutput,
    LLMMode,
    NewsEvent,
)
from src.provider_adapters.base import LLMProvider, ProviderError
from src.risk_policy import apply_advisory_policy
from src.sentiment.cache import LLMResponseCache, build_cache_key
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.prompt_builder import build_advisory_prompt, load_prompt_template
from src.sentiment.schemas import try_validate_payload


class AdvisoryEngine:
    """Generate structured advisory outputs while keeping deterministic strategy control primary."""

    def __init__(
        self,
        provider: LLMProvider | None,
        schema: dict,
        advisory_prompt_path,
        model_name: str,
        cache: LLMResponseCache,
        feature_store: SentimentFeatureStore,
        llm_mode: LLMMode,
        policy,
        cache_ttl_minutes: int,
        daily_budget_usd: float,
        estimated_request_cost_usd: float,
    ) -> None:
        self.provider = provider
        self.schema = schema
        self.advisory_prompt_path = advisory_prompt_path
        self.model_name = model_name
        self.cache = cache
        self.feature_store = feature_store
        self.llm_mode = llm_mode
        self.policy = policy
        self.cache_ttl_minutes = cache_ttl_minutes
        self.daily_budget_usd = daily_budget_usd
        self.estimated_request_cost_usd = estimated_request_cost_usd
        self.logger = get_logger("quant_gpt.llm")

    def _hash_response(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def evaluate(
        self,
        context: DeterministicDecisionContext,
        events: list[NewsEvent],
    ) -> LLMAdvisoryOutput | None:
        """Return a validated advisory output or None on fail-open conditions."""

        if self.llm_mode == LLMMode.DISABLED or not events:
            return None

        system_prompt = load_prompt_template(self.advisory_prompt_path)
        prompt, prompt_version = build_advisory_prompt(system_prompt, context, events)
        cache_key = build_cache_key(context.symbol, self.model_name, prompt_version, prompt)

        cached = self.cache.get(cache_key)
        if cached is not None:
            advisory, error = try_validate_payload(cached, self.schema)
            if advisory is not None:
                self.cache.store.record_llm_usage(self.model_name, context.symbol, 0.0, cache_hit=True)
                self.logger.info("advisory cache_hit symbol=%s model=%s", context.symbol, self.model_name)
                return advisory
            self.logger.warning("Cached advisory failed validation for %s: %s", context.symbol, error)

        if self.provider is None:
            return None

        current_spend = self.cache.store.daily_llm_spend()
        if current_spend + self.estimated_request_cost_usd > self.daily_budget_usd:
            self.logger.warning(
                "Advisory budget exceeded symbol=%s spend=%.4f budget=%.4f",
                context.symbol,
                current_spend,
                self.daily_budget_usd,
            )
            return None

        try:
            payload = self.provider.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
                schema=self.schema,
                model_name=self.model_name,
            )
        except ProviderError as exc:
            self.logger.warning("Advisory provider failed for %s: %s", context.symbol, exc)
            return None

        payload.setdefault("model_name", self.model_name)
        payload.setdefault("prompt_version", prompt_version)
        advisory, error = try_validate_payload(payload, self.schema)
        if advisory is None:
            self.logger.warning("Advisory validation failed for %s: %s", context.symbol, error)
            return None

        advisory = LLMAdvisoryOutput(**{**advisory.model_dump(mode="python"), "response_hash": self._hash_response(payload)})
        self.cache.put(
            cache_key=cache_key,
            provider=self.provider.provider_name(),
            model_name=self.model_name,
            prompt_version=prompt_version,
            response_hash=advisory.response_hash or "",
            payload=advisory.model_dump(mode="json"),
            ttl_minutes=self.cache_ttl_minutes,
        )
        self.cache.store.record_llm_usage(
            model_name=self.model_name,
            symbol=context.symbol,
            estimated_cost_usd=self.estimated_request_cost_usd,
            cache_hit=False,
        )
        self.logger.info("advisory cache_miss symbol=%s model=%s", context.symbol, self.model_name)
        return advisory

    def evaluate_with_policy(
        self,
        context: DeterministicDecisionContext,
        events: list[NewsEvent],
    ) -> AdvisoryEnvelope | None:
        """Evaluate an advisory and apply deterministic policy bounds."""

        advisory = self.evaluate(context, events)
        if advisory is None:
            return None

        decision = apply_advisory_policy(
            base_weight=context.target_weight,
            advisory=advisory,
            mode=self.llm_mode,
            policy=self.policy,
        )
        envelope = AdvisoryEnvelope(advisory=advisory, decision=decision)
        self.feature_store.save_advisory(envelope, policy_mode=self.llm_mode.value)
        return envelope
