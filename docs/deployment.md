# Deployment Plan

## Scope

This deployment plan covers a Raspberry Pi 5 bare-metal-first setup with LEAN workspace compatibility and optional Docker-backed LEAN engine execution if required by the local engine/runtime combination.

## Deployment Modes

### 1. Development / Local Validation

Purpose:

- bootstrap the environment
- validate imports, config loading, and tests
- exercise LLM contract checks without live credentials

Primary commands:

- `make setup`
- `make env`
- `make verify`
- `make test`
- `make smoke`

### 2. Backtest Mode

Purpose:

- run LEAN-compatible backtests locally
- direct output artefacts to the NVMe-backed project path
- preserve result bundles and audit logs

Execution path:

- bare-metal project tooling always
- LEAN CLI if installed
- optional engine image only if LEAN requires it

Primary command:

- `make backtest`

### 3. Paper Trading Mode

Purpose:

- exercise the runtime under real scheduling and provider credentials without live capital
- validate restart safety, state persistence, and operator procedures

Primary command:

- `make live-paper`

### 4. Live Provider Mode

Purpose:

- prepare for real execution only after the operator enables a configured provider and accepts the associated risk

Primary command:

- `scripts/run_live_provider.sh`

This mode will include explicit warnings and credential checks before continuing.

## Environment Preparation

### Stage A: Host Validation

The bootstrap script must verify:

- ARM64 architecture
- Python 3.11+ availability or install path
- free disk space and RAM
- writable project path
- system packages required for Python builds, SQLite, LEAN CLI, and shell tooling

### Stage B: Python Tooling

The environment will be provisioned with:

- local virtual environment under the project root
- pinned Python dependencies from `requirements.txt`
- `pipx` for CLI-style tools where practical
- non-destructive, re-runnable install steps

### Stage C: Secret Injection

The environment setup script will:

- prompt interactively for credentials
- mask sensitive values when supported
- write `.env` with permission `600`
- avoid overwriting existing values without confirmation

## Runtime Layout

All persistent outputs remain within the repository root:

- `logs/` for rotating operator and audit logs
- `state/` for SQLite and lock files
- `data/` for cached provider/LLM artefacts
- `results/` for backtest outputs and reports

## Safety Gates

Before any execution workflow starts, scripts must verify:

- configuration files exist
- `.env` is present when required
- `lean` is installed before LEAN workflows
- LEAN authentication is available before remote or credentialed operations
- provider mode is explicitly selected
- live execution requires operator confirmation

## Recovery and Restart

The runtime will be designed so that:

- rebalance cycles are idempotent per monthly key
- latest holdings and intent hashes are persisted
- process locks prevent duplicate launches
- state corruption surfaces clearly through health checks
- LLM failure does not block strategy execution

## Validation Milestones

1. Repository scaffolding complete
2. Pure Python modules import cleanly
3. SQLite initializes with WAL and schema migration
4. Shell scripts pass syntax checks
5. Pytest discovers the suite
6. LLM contract tests pass offline
7. Backtest script validates local LEAN prerequisites

## Credential and Data Dependencies

Full end-to-end operation remains blocked until the operator supplies:

- QuantConnect credentials for LEAN CLI where needed
- local LEAN-compatible data or a selected alternative provider
- Gemini or alternate LLM credentials if advisory mode is enabled
- broker credentials for paper or live execution

## Final Operator Workflow

1. Bootstrap the Pi host
2. Create `.env`
3. Verify installation
4. Run unit and integration tests
5. Run smoke tests
6. Run backtests
7. Enable paper trading
8. Review audit and advisory outputs
9. Consider guarded live provider activation only after successful paper validation
