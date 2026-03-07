# Architecture Plan

## Objective

Build a self-hosted, LEAN-compatible quant trading stack optimized for Raspberry Pi 5 ARM64 Linux, with all runtime state, logs, caches, and artefacts rooted under the project directory. The stack preserves the existing QuantConnect strategy behaviour as closely as practical while adding:

- local operational hardening
- deterministic restart-safe execution
- provider abstraction for data and execution
- optional, auditable LLM advisory support

## Constraints

- Target hardware: Raspberry Pi 5, 8 GB RAM, ARM64 Linux
- Preferred runtime: bare metal first
- Docker: optional compatibility path only if required for LEAN engine execution
- Secrets: environment-driven only, never committed
- Data fidelity: first-class concern; documented drift where exact parity is not possible
- Determinism: strategy outputs must remain reproducible without LLM influence

## Repository Layers

### 1. Strategy Layer

Responsibilities:

- LEAN algorithm entrypoint and workspace integration
- configuration-driven thresholds, weights, and portfolio construction
- pure scoring and timing logic separated from LEAN runtime classes
- deterministic rebalance intent generation
- guarded integration point for optional LLM advisory features

Modules:

- `src/scoring.py`
- `src/timing.py`
- `src/risk_policy.py`
- `src/main.py`
- `lean_workspace/QualityGrowthPi/main.py`

### 2. Domain Layer

Responsibilities:

- typed data contracts
- no direct infrastructure concerns
- minimal LEAN coupling

Key models:

- fundamental snapshots
- timing state
- ranked candidates
- rebalance intents
- audit events
- news items
- sentiment features
- narrative tags
- advisory outputs
- risk flags

Modules:

- `src/models.py`

### 3. Infrastructure Layer

Responsibilities:

- settings and environment loading
- SQLite WAL persistence
- structured logging and audit trails
- provider adapters and runtime abstractions
- startup checks, health, locking, recovery
- LLM adapters, schema validation, prompt loading, and cache metadata

Modules:

- `src/settings.py`
- `src/state_store.py`
- `src/logging_utils.py`
- `src/audit.py`
- `src/health.py`
- `src/provider_adapters/*`
- `src/sentiment/cache.py`
- `src/sentiment/schemas.py`

### 4. Tooling Layer

Responsibilities:

- Pi bootstrap and environment setup
- install verification
- backtest, paper trading, and live execution wrappers
- smoke tests and LLM health checks
- operator workflows

Modules:

- `scripts/bootstrap_pi.sh`
- `scripts/setup_env.sh`
- `scripts/verify_install.sh`
- `scripts/run_backtest.sh`
- `scripts/run_live_paper.sh`
- `scripts/run_live_provider.sh`
- `scripts/smoke_test.sh`
- `scripts/llm_healthcheck.sh`

### 5. Testing Layer

Responsibilities:

- unit tests for pure logic
- integration tests for persistence and runtime guards
- regression scaffolding for later baseline comparison
- LLM contract and fail-open tests

Modules:

- `tests/unit/*`
- `tests/integration/*`
- `tests/regression/*`
- `tests/llm/*`

## Strategy Preservation Requirements

The primary production algorithm must preserve these behaviours:

- dynamic US equity fundamental universe
- explicit `SPY` subscription for deterministic schedule anchoring
- bootstrap history for timing state when new symbols join the universe
- stale data protection before rebalance
- restart-safe monthly rebalance idempotency
- safer parameter parsing and externalized config
- extracted pure scoring functions for unit testing
- structured audit logs and order event logging

## Provider Model

The system will implement a provider abstraction with four modes:

1. `quantconnect_local`
   - highest-fidelity mode when licensed local LEAN-compatible data is available
2. `external_equivalent`
   - approximate mode using external data providers
3. `paper_trading`
   - preferred live onboarding mode
4. `llm_advisory`
   - optional additive enrichment

Known fidelity risks to document and test:

- Morningstar field equivalence
- point-in-time correctness
- symbol mapping and ticker changes
- split and dividend treatment
- survivorship bias
- live data latency drift
- provider schema mismatches

## LLM Advisory Design

The LLM subsystem is advisory-only by default and must never place orders directly. It will:

- ingest curated text/news inputs
- produce schema-validated JSON outputs only
- store prompts, response hashes, model names, parsed payloads, and downstream effects
- support `observe_only`, `advisory_only`, and bounded `risk_modifier` modes
- fail open so deterministic strategy execution continues if the LLM path is down

The default model family will be configurable and adapter-driven, with Gemini 3.1 Flash-Lite Preview as the initial low-cost default when configured by the operator.

## Persistence and Recovery

SQLite in WAL mode under `state/` will be used for:

- rebalance idempotency
- holdings snapshots
- audit event storage
- provider cache metadata
- advisory history
- LLM cache metadata

Operational controls:

- single-process runtime lock
- startup banner and heartbeat
- bounded retries and timeouts
- graceful shutdown hooks
- advisory cache pruning

## Implementation Sequence

1. Create planning docs first
2. Scaffold repository layout and baseline configs
3. Implement pure Python domain and strategy logic
4. Implement persistence, logging, and provider abstractions
5. Implement LEAN workspace entrypoint and sync-friendly shared code usage
6. Implement LLM advisory subsystem and safety policy gates
7. Implement operational scripts
8. Implement tests and fixtures
9. Run sanity checks and repair failures

## Deliverable Standard

Every generated file must contain meaningful initial content. Credential-dependent sections may remain inert until the operator supplies local secrets or data licenses, but the repository itself must be runnable for local validation, tests, and smoke checks without hidden placeholders.
