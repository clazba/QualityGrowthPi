# QualityGrowthPi

Self-hosted LEAN-compatible quant trading stack for Raspberry Pi 5, designed to preserve a QuantConnect-style quality-growth US equities strategy while adding local operational hardening, persistence, regression testing, and an optional auditable LLM advisory subsystem.

## Key Properties

- bare-metal-first Python tooling
- LEAN workspace compatibility under `lean_workspace/`
- deterministic strategy logic extracted into testable Python modules
- SQLite WAL state store for restart safety and auditability
- optional LLM advisory path with strict policy gating and fail-open behaviour
- NVMe-oriented runtime layout for logs, results, state, and caches

## Layout

- `src/`: shared Python modules, persistence, risk policy, providers, and LLM advisory components
- `lean_workspace/`: LEAN project layout and algorithm entrypoint
- `scripts/`: Pi bootstrap, environment setup, verification, test, and execution scripts
- `config/`: YAML configuration and local prompt templates
- `tests/`: unit, integration, regression, and LLM contract tests
- `docs/`: architecture, operations, deployment, provider fidelity, security, and LLM design notes

## Target Runtime

The intended Pi deployment path is `/mnt/nvme_data/shared/quant_gpt`. This scaffold is generated in the current workspace path and uses repository-relative defaults so it can be validated locally first. On the Pi, set `QUANT_GPT_RUNTIME_ROOT=/mnt/nvme_data/shared/quant_gpt` in `.env`.

## Fast Start

```bash
make setup
make env
make verify
make test
make smoke
make llm-smoke
make e2e
```

For an operator-focused setup and usage guide, see [docs/quickstart.md](/Volumes/PiShare/quant_gpt/docs/quickstart.md).

## Execution Paths

- Backtest: `make backtest` (`QuantConnect cloud` is the default and validated path)
- Operator workflow: `make workflow` (builds the deterministic opportunity report, loads recent news, runs LLM advisory review for current paper candidates, and writes a markdown report under `results/opportunities/`)
- Paper trading: `make paper-check`, `./scripts/list_qc_nodes.sh`, `make live-paper`, `make paper-status`, `make paper-stop` (`Alpaca paper` via `QuantConnect cloud + Alpaca brokerage` is the default first stage)
- LLM advisory history: `make llm-report`
- Live provider path: `scripts/run_live_provider.sh`
- Baseline capture: `make baseline BACKTEST_ID=<cloud_backtest_id>`

## Validated Operator Flow

The repository has been validated on the Pi for:

- cloud backtests with QuantConnect project sync via API
- cloud paper deployment with Alpaca brokerage
- online end-to-end validation via `./scripts/run_e2e.sh --online`
- regression and unit coverage across the shared control plane and LEAN workspace

Typical operator sequence:

```bash
make verify
make test
make backtest
make paper-check
./scripts/list_qc_nodes.sh
make live-paper
make paper-status
```

## Current Limits

- cloud backtests can bypass local dataset downloads while keeping the repository on-prem; fully local backtests still require licensed local-compatible datasets
- cloud Alpaca paper deployment requires an available QuantConnect live node; `Quant Researcher` allows live-node usage but does not automatically provision one for free
- the first local fallback stack is Massive + SEC + Alpaca + Alpha Vantage, which is designed for staged paper/live approximation rather than exact QuantConnect parity
- provider adapters for Massive, Alpaca, Alpha Vantage, SEC, IBKR, and Gemini are scaffolded with safety guards and offline fallbacks, not fully credentialed here
- LEAN engine execution depends on the local host having `lean` installed and authenticated

See [docs/architecture.md](/Volumes/PiShare/quant_gpt/docs/architecture.md), [docs/deployment.md](/Volumes/PiShare/quant_gpt/docs/deployment.md), and [docs/data-providers.md](/Volumes/PiShare/quant_gpt/docs/data-providers.md).
