"""Operator workflow helpers for deterministic and advisory reporting."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from src.models import DeterministicDecisionContext, PairPositionState
from src.provider_adapters.alpha_vantage_adapter import AlphaVantageNewsProvider
from src.provider_adapters.base import ProviderError
from src.provider_adapters.composite import CompositeNewsProvider
from src.provider_adapters.factory import build_market_data_provider, build_news_provider
from src.provider_adapters.gemini_api_adapter import GeminiAPIAdapter
from src.provider_adapters.news_base import FileNewsProvider, MassiveNewsProvider
from src.stat_arb import collect_price_history, run_stat_arb_cycle
from src.sentiment import AdvisoryEngine
from src.sentiment.cache import LLMResponseCache
from src.sentiment.feature_store import SentimentFeatureStore
from src.sentiment.schemas import load_schema
from src.settings import Settings, resolve_project_path
from src.state_store import StateStore


def fetch_alpaca_account_and_positions() -> dict[str, Any]:
    """Return Alpaca account + positions for operator reporting."""

    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    base_url = (os.getenv("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets") or "").rstrip("/")

    if not api_key or not api_secret:
        return {"available": False, "reason": "missing_credentials"}

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    session = requests.Session()
    try:
        account_response = session.get(f"{base_url}/v2/account", headers=headers, timeout=15)
        account_response.raise_for_status()
        positions_response = session.get(f"{base_url}/v2/positions", headers=headers, timeout=15)
        positions_response.raise_for_status()
    except requests.RequestException as exc:
        body = ""
        if "positions_response" in locals():
            body = positions_response.text[:500]
        elif "account_response" in locals():
            body = account_response.text[:500]
        return {"available": False, "reason": f"request_failed: {exc}", "body": body}

    payload = positions_response.json()
    positions = payload if isinstance(payload, list) else []
    account = account_response.json() if account_response.content else {}
    return {
        "available": True,
        "account": account,
        "position_count": len(positions),
        "positions": positions,
    }


def build_candidate_contexts(
    positions_payload: dict[str, Any],
    max_symbols: int,
) -> list[DeterministicDecisionContext]:
    """Convert current Alpaca paper positions into advisory contexts."""

    if not positions_payload.get("available"):
        return []

    account = positions_payload.get("account", {})
    try:
        account_equity = float(account.get("equity", 0) or 0)
    except (TypeError, ValueError):
        account_equity = 0.0

    positions = list(positions_payload.get("positions", []))
    positions.sort(key=lambda item: abs(float(item.get("market_value", 0) or 0)), reverse=True)

    contexts: list[DeterministicDecisionContext] = []
    for item in positions[:max_symbols]:
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        try:
            market_value = float(item.get("market_value", 0) or 0)
        except (TypeError, ValueError):
            market_value = 0.0
        target_weight = abs(market_value) / account_equity if account_equity > 0 else 0.0
        notes = [
            "Context derived from current Alpaca paper holdings.",
            f"market_value={item.get('market_value', '0')}",
            f"qty={item.get('qty', '0')}",
            f"side={item.get('side', 'unknown')}",
            f"unrealized_plpc={item.get('unrealized_plpc', '0')}",
        ]
        contexts.append(
            DeterministicDecisionContext(
                symbol=symbol,
                fundamental_score=0.0,
                timing_score=0.0,
                combined_score=0.0,
                target_weight=round(target_weight, 6),
                notes=notes,
            )
        )
    return contexts


def build_pair_trade_contexts(stat_arb_summary: dict[str, Any]) -> list[DeterministicDecisionContext]:
    """Convert accepted stat-arb intents into symbol-level advisory contexts."""

    contexts: list[DeterministicDecisionContext] = []
    seen_symbols: set[str] = set()
    for intent in stat_arb_summary.get("accepted_intents", []):
        for symbol, weight, notes in (
            (
                intent["long_symbol"],
                abs(float(intent["long_weight"])),
                [
                    "Stat-arb pair long leg.",
                    f"pair_id={intent['pair_id']}",
                    f"expected_edge_bps={intent['expected_edge_bps']}",
                ],
            ),
            (
                intent["short_symbol"],
                abs(float(intent["short_weight"])),
                [
                    "Stat-arb pair short leg.",
                    f"pair_id={intent['pair_id']}",
                    f"expected_edge_bps={intent['expected_edge_bps']}",
                ],
            ),
        ):
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            contexts.append(
                DeterministicDecisionContext(
                    symbol=symbol,
                    fundamental_score=0.0,
                    timing_score=0.0,
                    combined_score=0.0,
                    target_weight=round(weight, 6),
                    notes=notes,
                )
            )
    return contexts


def _build_llm_provider(settings: Settings):
    if not settings.llm.enabled:
        return None
    if settings.llm.provider.strip().lower() != "gemini":
        return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    return GeminiAPIAdapter(
        api_key=api_key,
        timeout_seconds=settings.llm.timeout_seconds,
    )


def _build_operator_news_provider(settings: Settings):
    configured_provider = build_news_provider(settings)
    providers = [configured_provider]

    if settings.local_data_stack.news_provider.value != "composite":
        fallback_providers = [
            FileNewsProvider(Path(os.getenv("NEWS_FEED_PATH", str(settings.data_dir / "news_cache" / "news_feed.jsonl")))),
            AlphaVantageNewsProvider(),
            MassiveNewsProvider(),
        ]
        seen_names = {provider.provider_name() for provider in providers}
        for provider in fallback_providers:
            if provider.provider_name() not in seen_names:
                providers.append(provider)
                seen_names.add(provider.provider_name())

    if len(providers) == 1:
        return providers[0]
    return CompositeNewsProvider(providers)


def run_operator_advisories(
    settings: Settings,
    store: StateStore,
    contexts: list[DeterministicDecisionContext],
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Load recent news, evaluate advisory outputs, and persist them."""

    result: dict[str, Any] = {
        "enabled": settings.llm.enabled,
        "mode": settings.llm.mode.value,
        "provider": settings.llm.provider,
        "evaluated_symbols": [],
        "news_event_count": 0,
        "news_events_by_symbol": {},
        "saved_advisories": [],
        "status": "not_requested",
    }

    if not settings.llm.enabled:
        result["status"] = "disabled"
        return result

    if not contexts:
        result["status"] = "no_candidates"
        return result

    symbols = [context.symbol for context in contexts]
    news_provider = _build_operator_news_provider(settings)
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    try:
        events = news_provider.fetch_news(symbols=symbols, since=since)
    except ProviderError as exc:
        result["status"] = f"news_unavailable: {exc}"
        return result
    grouped_events: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        grouped_events[event.symbol].append(event)

    result["news_event_count"] = len(events)
    result["news_events_by_symbol"] = {symbol: len(grouped_events.get(symbol, [])) for symbol in symbols}
    if not events:
        result["status"] = "no_recent_news"
        return result

    provider = _build_llm_provider(settings)
    if provider is None:
        result["status"] = "provider_unavailable"
        return result

    schema = load_schema(Path(settings.prompts_dir) / settings.llm.prompts.extraction_schema)
    advisory_prompt_path = Path(settings.prompts_dir) / settings.llm.prompts.advisory
    engine = AdvisoryEngine(
        provider=provider,
        schema=schema,
        advisory_prompt_path=advisory_prompt_path,
        model_name=settings.llm.default_model,
        cache=LLMResponseCache(store),
        feature_store=SentimentFeatureStore(store),
        llm_mode=settings.llm.mode,
        policy=settings.llm.policy,
        cache_ttl_minutes=settings.llm.cache_ttl_minutes,
        daily_budget_usd=settings.llm.budget_usd_daily,
        estimated_request_cost_usd=settings.llm.estimated_request_cost_usd,
    )

    saved_advisories = []
    for context in contexts:
        symbol_events = grouped_events.get(context.symbol, [])
        if not symbol_events:
            continue
        envelope = engine.evaluate_with_policy(context, symbol_events)
        result["evaluated_symbols"].append(context.symbol)
        if envelope is None:
            continue
        saved_advisories.append(
            {
                "symbol": envelope.advisory.symbol,
                "suggested_action": envelope.advisory.suggested_action.value,
                "confidence_score": envelope.advisory.confidence_score,
                "source_coverage_score": envelope.advisory.source_coverage_score,
                "sentiment_label": envelope.advisory.sentiment_label.value,
                "reason": envelope.decision.reason,
                "manual_review_required": envelope.decision.manual_review_required,
                "adjusted_weight": envelope.decision.adjusted_weight,
            }
        )

    result["saved_advisories"] = saved_advisories
    result["status"] = "ok" if saved_advisories else "no_advisories_saved"
    return result


def run_stat_arb_operator_cycle(
    settings: Settings,
    store: StateStore,
    portfolio_equity: float,
) -> dict[str, Any]:
    """Run the stat-arb research cycle, persist artifacts, and return a compact report."""

    provider = build_market_data_provider(settings)
    price_history, skipped_symbols = collect_price_history(provider, settings.stat_arb)
    if len(price_history) < 2:
        return {
            "status": "insufficient_market_data",
            "skipped_symbols": skipped_symbols,
            "clusters": [],
            "accepted_intents": [],
            "rejected_pairs": [],
            "exit_signals": [],
            "open_positions": store.open_pair_positions(),
        }

    open_positions = [PairPositionState(**row["payload"]) for row in store.open_pair_positions()]
    cycle = run_stat_arb_cycle(
        settings.stat_arb,
        price_history,
        portfolio_equity=portfolio_equity,
        open_positions=open_positions,
    )
    store.save_cluster_snapshots(cycle.clusters)
    intents_by_pair = {intent.pair_id: intent for intent in cycle.intents}
    for candidate in cycle.candidates:
        decision = cycle.decisions.get(candidate.pair_id)
        intent = intents_by_pair.get(candidate.pair_id)
        store.save_pair_opportunity(
            as_of=cycle.as_of,
            candidate=candidate,
            status="accepted" if intent is not None else "rejected",
            decision=decision,
            intent=intent,
            metadata={"strategy_mode": settings.runtime.strategy_mode.value},
        )

    accepted_intents = [intent.model_dump(mode="json") for intent in cycle.intents]
    rejected_pairs = [
        {
            "pair_id": candidate.pair_id,
            "cluster_id": candidate.cluster_id,
            "z_score": candidate.spread_features.z_score,
            "expected_edge_bps": candidate.spread_features.expected_edge_bps,
            "decision": cycle.decisions[candidate.pair_id].model_dump(mode="json"),
        }
        for candidate in cycle.candidates
        if not cycle.decisions[candidate.pair_id].execute
    ]
    return {
        "status": "ok",
        "summary": cycle.summary(),
        "ml_filter_status": dict(cycle.ml_filter_status),
        "clusters": [snapshot.model_dump(mode="json") for snapshot in cycle.clusters],
        "accepted_intents": accepted_intents,
        "rejected_pairs": rejected_pairs,
        "exit_signals": list(cycle.exits),
        "open_positions": [state.model_dump(mode="json") for state in open_positions],
        "skipped_symbols": skipped_symbols,
    }


def load_lean_strategy_config(config_path: Path) -> dict[str, Any]:
    """Load the cloud-safe LEAN config module."""

    namespace: dict[str, object] = {}
    resolved = resolve_project_path(config_path)
    exec(resolved.read_text(encoding="utf-8"), namespace)
    return namespace["CONFIG"]  # type: ignore[return-value]


def build_workflow_report(
    diagnostics: dict[str, Any],
    config: dict[str, Any],
    paper_status_text: str,
    positions_payload: dict[str, Any],
    llm_summary: dict[str, Any],
    stat_arb_summary: dict[str, Any] | None = None,
) -> str:
    """Render the operator-facing markdown report."""

    summary = diagnostics["summary"]
    runtime = summary.get("runtime_statistics", {})
    statistics = summary.get("statistics", {})
    strategy = config["strategy"]
    thresholds = strategy["thresholds"]
    weights = strategy["weights"]
    timing = strategy["timing"]
    rebalance = strategy["rebalance"]
    universe = strategy["universe"]

    if stat_arb_summary is not None and "graph" in strategy:
        return _build_stat_arb_workflow_report(
            diagnostics=diagnostics,
            config=config,
            paper_status_text=paper_status_text,
            positions_payload=positions_payload,
            llm_summary=llm_summary,
            stat_arb_summary=stat_arb_summary,
        )

    target_count = int(runtime.get("LastSuccessfulTargetCount") or runtime.get("LastRebalanceTargetCount") or 0)
    ranked_count = int(runtime.get("LastUniverseRankedCount") or 0)
    fine_count = int(runtime.get("LastUniverseFineCount") or 0)

    if target_count == 0:
        opportunity_readout = (
            "No active target basket was produced in the latest validated run. "
            "The operator should inspect diagnostics before acting."
        )
    elif target_count < max(3, rebalance["max_holdings"] // 2):
        opportunity_readout = (
            "The strategy found a narrow opportunity set. "
            "Selection is active, but the market is only surfacing a limited number of high-conviction names."
        )
    else:
        opportunity_readout = (
            "The strategy found a healthy opportunity set. "
            "Fundamental screening, ranking, and timing all produced a full or near-full target basket."
        )

    positions_lines = []
    if positions_payload.get("available"):
        positions = list(positions_payload.get("positions", []))
        positions.sort(key=lambda item: float(item.get("market_value", 0) or 0), reverse=True)
        for item in positions[:10]:
            positions_lines.append(
                f"- `{item.get('symbol')}` qty={item.get('qty')} market_value={item.get('market_value')} side={item.get('side')}"
            )
    else:
        positions_lines.append(f"- positions unavailable: {positions_payload.get('reason', 'unknown')}")

    llm_lines = []
    if not llm_summary.get("enabled", False):
        llm_lines.append("- LLM subsystem is disabled.")
    elif llm_summary.get("status") == "no_candidates":
        llm_lines.append("- No current paper candidates were available for advisory evaluation.")
    elif llm_summary.get("status") == "no_recent_news":
        llm_lines.append("- No recent news was found for the current paper candidates.")
    elif str(llm_summary.get("status", "")).startswith("news_unavailable:"):
        llm_lines.append(f"- {llm_summary['status']}")
    elif llm_summary.get("status") == "provider_unavailable":
        llm_lines.append("- LLM provider is unavailable. Check Gemini configuration.")
    elif llm_summary.get("status") == "no_advisories_saved":
        llm_lines.append("- Candidate news was loaded, but no advisories were saved.")
    else:
        llm_lines.append(
            f"- evaluated symbols: `{', '.join(llm_summary.get('evaluated_symbols', [])) or 'none'}`"
        )
        llm_lines.append(f"- recent news events: `{llm_summary.get('news_event_count', 0)}`")
        for advisory in llm_summary.get("saved_advisories", [])[:10]:
            llm_lines.append(
                "- `{symbol}` action={action} sentiment={label} confidence={confidence:.2f} "
                "coverage={coverage:.2f} manual_review={manual_review}".format(
                    symbol=advisory["symbol"],
                    action=advisory["suggested_action"],
                    label=advisory["sentiment_label"],
                    confidence=float(advisory["confidence_score"]),
                    coverage=float(advisory["source_coverage_score"]),
                    manual_review=str(advisory["manual_review_required"]).lower(),
                )
            )

    return f"""# Trade Workflow Report

## 1. Fundamental Universe

- exchange: `{universe['exchange_id']}`
- minimum market cap: `{universe['min_market_cap']}`
- minimum price: `{universe['min_price']}`
- require fundamentals: `{universe['require_fundamental_data']}`
- latest fine universe count: `{fine_count}`

## 2. Quality-Growth Ranking

- ROE minimum: `{thresholds['roe_min']}`
- gross margin minimum: `{thresholds['gross_margin_min']}`
- debt/equity range: `({thresholds['debt_to_equity_min']}, {thresholds['debt_to_equity_max']}]`
- revenue growth minimum: `{thresholds['revenue_growth_min']}`
- net income growth minimum: `{thresholds['net_income_growth_min']}`
- PEG range: `({thresholds['peg_ratio_min']}, {thresholds['peg_ratio_max']}]`
- ranked candidate count: `{ranked_count}`
- fundamental weights: `roe={weights['roe']}, revenue_growth={weights['revenue_growth']}, net_income_growth={weights['net_income_growth']}, inverse_peg={weights['inverse_peg']}`

## 3. Timing Filters

- volume window: `{timing['volume_window']}`
- price window: `{timing['price_window']}`
- short SMA: `{timing['short_sma']}`
- long SMA: `{timing['long_sma']}`
- relative volume threshold: `{timing['relative_volume_threshold']}`
- volatility contraction threshold: `{timing['volatility_contraction_threshold']}`
- latest timing feature count: `{runtime.get('LastTimingFeatureCount', '0')}`

## 4. Monthly Target Holdings

- max holdings: `{rebalance['max_holdings']}`
- candidate pool multiplier: `{rebalance['candidate_pool_multiplier']}`
- last rebalance state: `{runtime.get('LastRebalanceCheckState', 'unknown')}`
- last successful rebalance key: `{runtime.get('LastSuccessfulRebalanceKey', 'n/a')}`
- latest target count: `{target_count}`

## 5. Cloud Backtest Validation

- backtest id: `{summary['backtest_id']}`
- backtest name: `{summary['name']}`
- backtest url: `{summary['backtest_url']}`
- status: `{summary['status']}`
- return: `{runtime.get('Return', statistics.get('Net Profit', 'n/a'))}`
- end equity: `{statistics.get('End Equity', runtime.get('Equity', 'n/a'))}`
- total orders: `{summary.get('reported_total_orders', summary.get('order_count', 0))}`
- closed trades: `{summary.get('closed_trade_count', 0)}`

## 6. Alpaca Paper Validation

Current deployment status:

```text
{paper_status_text}
```

Current paper positions:

{chr(10).join(positions_lines)}

## 7. LLM Advisory Review

- mode: `{llm_summary.get('mode', 'unknown')}`
- provider: `{llm_summary.get('provider', 'unknown')}`
- status: `{llm_summary.get('status', 'unknown')}`
{chr(10).join(llm_lines)}

## 8. Operator Readout

{opportunity_readout}

Interpretation:
- Use the backtest diagnostics to confirm the strategy is still producing a viable target basket.
- Use the active Alpaca paper positions as the operational view of what the strategy currently wants to hold.
- Use the LLM advisory review as a secondary narrative and risk lens, not as the primary selector.
- If the target count collapses, advisories turn broadly negative, or paper positions drift materially from expectation, stop paper trading and investigate before acting further.
"""


def _build_stat_arb_workflow_report(
    diagnostics: dict[str, Any],
    config: dict[str, Any],
    paper_status_text: str,
    positions_payload: dict[str, Any],
    llm_summary: dict[str, Any],
    stat_arb_summary: dict[str, Any],
) -> str:
    """Render the operator report for the graph-clustered stat-arb strategy."""

    summary = diagnostics["summary"]
    runtime = summary.get("runtime_statistics", {})
    statistics = summary.get("statistics", {})
    strategy = config["strategy"]
    universe = strategy["universe"]
    graph = strategy["graph"]
    spread = strategy["spread"]
    exit_policy = strategy["exit_policy"]
    sizing = strategy["sizing"]
    ml_filter = strategy["ml_filter"]
    ml_filter_status = stat_arb_summary.get("ml_filter_status", cycle_summary.get("ml_filter_status", {}))

    cycle_summary = stat_arb_summary.get("summary", {})
    clusters = stat_arb_summary.get("clusters", [])
    accepted = stat_arb_summary.get("accepted_intents", [])
    rejected = stat_arb_summary.get("rejected_pairs", [])
    exits = stat_arb_summary.get("exit_signals", [])

    positions_lines = []
    if positions_payload.get("available"):
        positions = list(positions_payload.get("positions", []))
        positions.sort(key=lambda item: abs(float(item.get("market_value", 0) or 0)), reverse=True)
        for item in positions[:10]:
            positions_lines.append(
                f"- `{item.get('symbol')}` qty={item.get('qty')} market_value={item.get('market_value')} side={item.get('side')}"
            )
    else:
        positions_lines.append(f"- positions unavailable: {positions_payload.get('reason', 'unknown')}")

    llm_lines = []
    if not llm_summary.get("enabled", False):
        llm_lines.append("- LLM subsystem is disabled.")
    elif llm_summary.get("status") in {"no_candidates", "no_recent_news", "provider_unavailable", "no_advisories_saved"}:
        llm_lines.append(f"- status detail: {llm_summary.get('status')}")
    else:
        llm_lines.append(f"- evaluated symbols: `{', '.join(llm_summary.get('evaluated_symbols', [])) or 'none'}`")
        llm_lines.append(f"- recent news events: `{llm_summary.get('news_event_count', 0)}`")
        for advisory in llm_summary.get("saved_advisories", [])[:10]:
            llm_lines.append(
                "- `{symbol}` action={action} sentiment={label} confidence={confidence:.2f} "
                "coverage={coverage:.2f} manual_review={manual_review}".format(
                    symbol=advisory["symbol"],
                    action=advisory["suggested_action"],
                    label=advisory["sentiment_label"],
                    confidence=float(advisory["confidence_score"]),
                    coverage=float(advisory["source_coverage_score"]),
                    manual_review=str(advisory["manual_review_required"]).lower(),
                )
            )

    cluster_lines = [
        f"- `{cluster['cluster_id']}` symbols={', '.join(cluster['symbols'])} avg_corr={cluster['average_correlation']} edges={cluster['edge_count']}"
        for cluster in clusters[:10]
    ] or ["- no clusters met the current graph threshold"]

    accepted_lines = [
        f"- `{intent['pair_id']}` long=`{intent['long_symbol']}` short=`{intent['short_symbol']}` "
        f"entry_z={intent['entry_z_score']} kelly={intent['kelly_fraction']} gross={intent['gross_exposure']} edge_bps={intent['expected_edge_bps']}"
        for intent in accepted[:10]
    ] or ["- no pair trades passed the ML filter"]

    rejected_lines = [
        f"- `{pair['pair_id']}` z={pair['z_score']} edge_bps={pair['expected_edge_bps']} "
        f"prob={pair['decision']['predicted_win_probability']} confidence={pair['decision']['confidence_score']}"
        for pair in rejected[:10]
    ] or ["- no rejected pair signals were recorded"]

    exit_lines = [
        f"- `{signal['pair_id']}` reason={signal['reason']} current_z={signal['current_z_score']} "
        f"take_profit_z={signal['take_profit_z_score']} stop_loss_z={signal['stop_loss_z_score']}"
        for signal in exits[:10]
    ] or ["- no open-pair exit signals were evaluated"]

    if accepted:
        opportunity_readout = (
            "The stat-arb engine found actionable mean-reversion dislocations. "
            "Graph clustering, spread scoring, and the ML filter all produced deployable pair trades."
        )
    elif rejected:
        opportunity_readout = (
            "The stat-arb engine found candidate pairs, but the ML filter rejected the current dislocations. "
            "This usually reflects weak net edge after fees or unstable pair behavior."
        )
    else:
        opportunity_readout = (
            "The stat-arb engine did not find deployable pair trades in the current universe snapshot. "
            "Cluster quality or spread divergence may be too weak under the current thresholds."
        )

    return f"""# Trade Workflow Report

## 1. Stat-Arb Universe

- symbols in configured universe: `{len(universe['symbols'])}`
- lookback days: `{universe['lookback_days']}`
- minimum history days: `{universe['min_history_days']}`
- minimum price: `{universe['min_price']}`
- skipped symbols this cycle: `{', '.join(stat_arb_summary.get('skipped_symbols', [])) or 'none'}`

## 2. Graph Clusters

- correlation lookback days: `{graph['correlation_lookback_days']}`
- minimum correlation: `{graph['min_correlation']}`
- minimum cluster size: `{graph['min_cluster_size']}`
- maximum cluster size: `{graph['max_cluster_size']}`
- cycle cluster count: `{cycle_summary.get('clusters', {}).get('cluster_count', 0)}`

{chr(10).join(cluster_lines)}

## 3. Pair Signals

- entry z-score: `{spread['entry_z_score']}`
- take-profit z-score: `{spread['take_profit_z_score']}`
- stop-loss z-score: `{spread['stop_loss_z_score']}`
- maximum half-life days: `{spread['max_half_life_days']}`
- minimum expected edge bps: `{spread['min_expected_edge_bps']}`
- candidate pairs this cycle: `{cycle_summary.get('candidate_count', 0)}`

Accepted pair intents:

{chr(10).join(accepted_lines)}

Rejected pair signals:

{chr(10).join(rejected_lines)}

## 4. ML Filter And Kelly Sizing

- configured mode: `{ml_filter_status.get('configured_mode', ml_filter.get('mode', 'embedded_scorecard'))}`
- active mode: `{ml_filter_status.get('active_mode', ml_filter.get('mode', 'embedded_scorecard'))}`
- pinned object-store key: `{ml_filter_status.get('configured_model_key', ml_filter.get('object_store_model_key', '')) or 'not_configured'}`
- local model path: `{ml_filter_status.get('local_model_path', ml_filter.get('local_model_path', '')) or 'not_configured'}`
- model version: `{ml_filter['model_version']}`
- loaded model version: `{ml_filter_status.get('loaded_model_version', ml_filter['model_version'])}`
- feature schema version: `{ml_filter_status.get('feature_schema_version', ml_filter.get('feature_schema_version', 'stat_arb_v1'))}`
- fallback active: `{ml_filter_status.get('fallback_active', False)}`
- load status: `{ml_filter_status.get('load_status', 'unknown')}`
- probability threshold: `{ml_filter['probability_threshold']}`
- minimum confidence: `{ml_filter['min_confidence']}`
- max open pairs: `{sizing['max_open_pairs']}`
- max gross exposure per trade: `{sizing['max_gross_exposure_per_trade']}`
- max gross exposure total: `{sizing['max_gross_exposure_total']}`
- max net exposure total: `{sizing['max_net_exposure_total']}`
- accepted count: `{cycle_summary.get('accepted_count', 0)}`
- rejected count: `{cycle_summary.get('rejected_count', 0)}`
{f"- load error: `{ml_filter_status['last_error']}`" if ml_filter_status.get('last_error') else ""}

## 5. Dynamic Exit Policy

- initial take-profit z-score: `{exit_policy['initial_take_profit_z_score']}`
- minimum take-profit z-score: `{exit_policy['minimum_take_profit_z_score']}`
- initial stop-loss z-score: `{exit_policy['initial_stop_loss_z_score']}`
- minimum stop-loss z-score: `{exit_policy['minimum_stop_loss_z_score']}`
- decay half-life days: `{exit_policy['decay_half_life_days']}`
- max holding days: `{exit_policy['max_holding_days']}`

Current exit signals:

{chr(10).join(exit_lines)}

## 6. Cloud Backtest Validation

- backtest id: `{summary['backtest_id']}`
- backtest name: `{summary['name']}`
- backtest url: `{summary['backtest_url']}`
- status: `{summary['status']}`
- return: `{runtime.get('Return', statistics.get('Net Profit', 'n/a'))}`
- end equity: `{statistics.get('End Equity', runtime.get('Equity', 'n/a'))}`
- total orders: `{summary.get('reported_total_orders', summary.get('order_count', 0))}`
- closed trades: `{summary.get('closed_trade_count', 0)}`

## 7. Alpaca Paper Validation

Current deployment status:

```text
{paper_status_text}
```

Current paper positions:

{chr(10).join(positions_lines)}

## 8. LLM Advisory Review

- mode: `{llm_summary.get('mode', 'unknown')}`
- provider: `{llm_summary.get('provider', 'unknown')}`
- status: `{llm_summary.get('status', 'unknown')}`
{chr(10).join(llm_lines)}

## 9. Operator Readout

{opportunity_readout}

Interpretation:
- Use the cluster table to confirm the graph step is finding coherent groups rather than isolated names.
- Use accepted pair intents as the strategy's current trade proposal, not the raw rejected list.
- Use the ML filter and Kelly sections to understand why a pair was approved and how much capital it deserves.
- Use the exit section to see whether active pairs are approaching take-profit, stop-loss, or time-based exits before taking operational action.
"""
