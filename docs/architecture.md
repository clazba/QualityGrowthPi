# Architecture

## Overview

`quant_gpt` is two systems working together:

- a local control plane on the Pi
- a cloud-synced LEAN strategy project in `lean_workspace/QualityGrowthPi/`

The current validated operating model is:

- cloud backtests in QuantConnect
- cloud paper deployment in QuantConnect with Alpaca as the brokerage
- local operator validation, reporting, and persistence on the Pi
- an optional LLM advisory layer used for narrative review, not primary signal generation

## Main Components

### Deterministic Strategy Engine

This is the source of truth for trade selection. It:

- builds the fundamental universe
- ranks quality-growth candidates
- applies timing filters
- creates monthly target holdings
- blocks rebalances when prices are missing or data is stale

Key files:

- `src/scoring.py`
- `src/timing.py`
- `src/risk_policy.py`
- `lean_workspace/QualityGrowthPi/main.py`
- `lean_workspace/QualityGrowthPi/scoring.py`

### Local Control Plane

This handles local state, health checks, and reporting. It:

- loads settings from YAML and `.env`
- initializes and maintains the SQLite state store
- emits audit records and runtime heartbeats
- prints provider-plan and LLM history reports

Key files:

- `src/main.py`
- `src/settings.py`
- `src/state_store.py`
- `src/health.py`
- `src/audit.py`
- `src/logging_utils.py`

### Provider Layer

This isolates external systems so the rest of the repo can work against normalized interfaces.

Current provider roles:

- QuantConnect cloud for validated backtests and paper execution hosting
- Alpaca for paper brokerage and local account and position inspection
- Massive, Alpha Vantage, and SEC for local fallback data and operator-side news and fundamental review
- Gemini for structured advisory generation

Key files:

- `src/provider_adapters/`

### Operator Workflow Layer

This is the operator-facing glue. It can:

- run a fresh cloud backtest
- read cloud diagnostics
- inspect paper deployment status
- load current Alpaca paper positions
- build a markdown opportunity report
- run and persist LLM advisories for the current paper candidate set

Key files:

- `scripts/run_backtest.sh`
- `scripts/read_backtest_diagnostics.sh`
- `scripts/run_live_paper.sh`
- `scripts/paper_status.sh`
- `scripts/run_trade_workflow.sh`
- `src/operator_workflow.py`

### LLM Advisory Layer

This layer is optional and secondary by design. It:

- loads recent news for symbols under review
- builds prompts from local templates
- requests schema-shaped JSON from Gemini
- validates and conservatively repairs common alias-style payloads
- caches and stores advisory history in SQLite

Key files:

- `src/sentiment/advisory_engine.py`
- `src/sentiment/prompt_builder.py`
- `src/sentiment/schemas.py`
- `src/sentiment/cache.py`
- `src/sentiment/feature_store.py`
- `config/prompts/`

## Validated Execution Flows

### Cloud Backtest Flow

1. Local config is synced into `lean_workspace/`.
2. QuantConnect project files are synced by API.
3. `lean cloud backtest` runs the strategy remotely.
4. Local diagnostics are saved under `results/backtests/cloud/`.

### Cloud Paper Flow

1. Alpaca paper credentials are checked locally.
2. LEAN workspace and project config are synced.
3. QuantConnect cloud live deploy starts the paper algorithm.
4. Alpaca acts as the brokerage.
5. Local scripts inspect deployment state and paper positions.

### Operator Workflow Flow

1. Latest backtest diagnostics are loaded.
2. Current paper deployment status is loaded.
3. Current Alpaca paper positions are loaded.
4. Recent news is collected for the current symbols.
5. LLM advisories are evaluated in `observe_only` mode by default.
6. Markdown and JSON reports are written under `results/opportunities/`.

## Persistence

The local SQLite database in WAL mode under `state/` stores:

- rebalance guard state
- audit events
- LLM cache entries
- LLM usage data
- saved advisory history

Important property:

- `make workflow` and `make llm-report` use the same database, so advisories saved during a workflow run are immediately available in the report command

## Design Rules

- deterministic strategy logic remains primary
- the LLM never places orders directly
- malformed or missing LLM output must fail open
- cloud backtests are the default fidelity path
- cloud Alpaca paper is the first brokered validation stage
- local fallback providers are for approximation and operator support, not exact QuantConnect parity

## Current Practical Limits

- QuantConnect CLI cloud log retrieval is unreliable, so saved diagnostics JSON is the preferred inspection path
- cloud paper deployment requires a QuantConnect live node even when Alpaca is the broker
- the local fallback stack is useful for operator review and staged local approximation, not strict Morningstar or QuantConnect parity
