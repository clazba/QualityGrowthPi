# Quickstart

This guide explains the normal operator workflow for the repository under `/mnt/nvme_data/shared/quant_gpt`.

## What This App Does

This repository is a local control plane and LEAN-compatible workspace for a quality-growth US equities strategy.

The default operating model is:

- backtests in `QuantConnect cloud`
- first paper deployment through `Alpaca paper`
- optional local fallback data stack using `Massive + SEC + Alpaca + Alpha Vantage`
- optional LLM advisory running in `observe_only` mode unless you explicitly tighten or enable influence

## Repository Entry Points

Use these commands from the repository root:

```bash
cd /mnt/nvme_data/shared/quant_gpt
```

Primary commands:

- `make setup`
  - bootstraps the Pi host, creates `.venv`, and installs Python tooling
- `make env`
  - creates or updates `.env`
- `make verify`
  - checks Python, imports, shell scripts, and pytest collection
- `make test`
  - runs the full regression suite
- `make smoke`
  - runs a fast control-plane smoke test
- `make llm-smoke`
  - runs LLM contract and health checks
- `make backtest`
  - runs the default `lean cloud backtest` flow
- `make live-paper`
  - runs the default `lean cloud live deploy` flow for `Alpaca paper`
- `make e2e`
  - runs the end-to-end validation harness with non-destructive defaults

## First-Time Setup

### 1. Bootstrap the machine

```bash
make setup
```

This should:

- validate the Pi host
- create `.venv`
- install Python dependencies
- install or validate LEAN CLI support

### 2. Create the environment file

```bash
make env
```

Recommended values for the first working setup:

- `BACKTEST_MODE=cloud`
- `PAPER_DEPLOYMENT_TARGET=cloud`
- `PAPER_BROKER=alpaca`
- `PAPER_ENVIRONMENT=paper`
- `QUANT_GPT_PROVIDER_MODE=external_equivalent`
- `LOCAL_FUNDAMENTALS_PROVIDER=massive_sec_alpha_vantage`
- `LOCAL_DAILY_BARS_PROVIDER=alpaca`
- `NEWS_PROVIDER_MODE=composite`
- `LLM policy mode=observe_only`

Leave provider keys blank if you are not using that provider yet. The deterministic strategy still works without the optional LLM and local-fallback providers being fully enabled.

### 3. Verify the install

```bash
make verify
```

Expected outcome:

- Python interpreter is detected correctly
- `.venv` is preferred if present
- required packages import
- tests are discoverable
- shell scripts parse cleanly

### 4. Run the test suite

```bash
make test
```

You should see the full suite pass before trying backtests or paper deployment.

## Day-One Validation

### Fast smoke test

```bash
make smoke
```

This runs:

- `python -m src.main health`
- `python -m src.main provider-plan`
- a focused scoring/timing test subset

### LLM smoke test

```bash
make llm-smoke
```

Use this even if the LLM remains non-trading. It verifies:

- schema contracts
- prompt loading
- fail-open behavior
- health-check wiring

### End-to-end pipeline test

```bash
make e2e
```

Default behavior:

- uses an isolated runtime root under `results/e2e/runtime`
- runs verification, data-directory prep, control-plane checks, smoke tests, LLM checks, and the full regression suite
- validates SQLite WAL state, provider-plan resolution, fixture news ingestion, and LEAN workspace sync when available
- performs backtest and paper-deployment preflight only, then aborts safely before execution

Optional online mode:

```bash
./scripts/run_e2e.sh --online
```

Optional execution mode:

```bash
./scripts/run_e2e.sh --online --run-cloud-backtest
./scripts/run_e2e.sh --online --run-paper-deploy
```

Those execution flags are intentionally explicit and still prompt for operator confirmation.

### Capture A Cloud Regression Baseline

After a successful cloud backtest, save the structured artefacts into the LEAN workspace regression bundle:

```bash
./scripts/read_backtest_diagnostics.sh <backtest_id>
make baseline BACKTEST_ID=<backtest_id>
```

This writes a baseline bundle under:

- `lean_workspace/QualityGrowthPi/tests/regression/cloud_baselines/<backtest_id>/`

And updates:

- `lean_workspace/QualityGrowthPi/tests/regression/baseline_manifest.json`

## How To Inspect The App

The local control-plane entrypoint is [src/main.py](/Volumes/PiShare/quant_gpt/src/main.py).

Useful commands:

```bash
. .venv/bin/activate
python -m src.main health
python -m src.main init-db
python -m src.main provider-plan
python -m src.main llm-report
```

What they do:

- `health`
  - initializes logging, state store, runtime lock, and emits a startup heartbeat
- `init-db`
  - initializes the SQLite state store under `state/`
- `provider-plan`
  - prints the resolved plan for backtest, paper broker, and local fallback providers
- `llm-report`
  - prints the latest advisory records from SQLite

## Backtesting Workflow

The repository default is `QuantConnect cloud`.

Run:

```bash
make backtest
```

What happens:

1. `.env` is loaded
2. LEAN CLI is checked
3. `lean_workspace/lean.json` is synced from local config
4. you are prompted for confirmation
5. the repo runs `lean cloud backtest QualityGrowthPi --push` by default

Use this mode when you want:

- QuantConnect-hosted historical data
- no local LEAN data downloads
- the local repository to remain the source of truth

If you intentionally want local backtests later, set `BACKTEST_MODE=local` and provide the required local datasets first.

## Paper Trading Workflow

The repository default first paper stage is `Alpaca paper` via LEAN cloud deployment.

Before running paper deployment, ensure `.env` contains:

- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `PAPER_BROKER=alpaca`
- `PAPER_ENVIRONMENT=paper`

Run:

```bash
make live-paper
```

What happens:

1. `.env` is loaded
2. LEAN CLI is checked
3. Alpaca credentials are validated
4. `lean_workspace/lean.json` is synced
5. you are prompted for confirmation
6. the repo runs `lean cloud live deploy` for the `QualityGrowthPi` project

This is the recommended first brokered stage before any real-money workflow.

## Local Fallback Data Stack

If you later need local provider-backed operation instead of full QuantConnect-hosted data, the intended first stack is:

- `Massive` for structured market and financial data
- `SEC` for public filing-derived fundamentals and validation
- `Alpaca` for daily bars and execution alignment
- `Alpha Vantage` for enrichment, news, and fallback reference data

Useful local cache locations:

- `/mnt/nvme_data/shared/quant_gpt/data/market_cache/massive/`
- `/mnt/nvme_data/shared/quant_gpt/data/market_cache/sec/`
- `/mnt/nvme_data/shared/quant_gpt/data/market_cache/alpha_vantage/`
- `/mnt/nvme_data/shared/quant_gpt/data/market_cache/alpaca/`
- `/mnt/nvme_data/shared/quant_gpt/data/news_cache/`

Prepare those directories with:

```bash
./scripts/download_data.sh
```

That script prepares the cache layout even when backtests remain cloud-based.

## Logs, State, And Results

Key runtime directories:

- `logs/`
  - rotating application, audit, and advisory logs
- `state/`
  - SQLite database and lock/state artifacts
- `results/`
  - backtest outputs and generated reports
- `data/`
  - provider caches, news feeds, and LLM caches

Useful operator checks:

```bash
ls -lah logs
ls -lah state
ls -lah results
```

## Typical Operator Workflows

### Clean install on a Pi

```bash
cd /mnt/nvme_data/shared/quant_gpt
make setup
make env
make verify
make test
make smoke
make llm-smoke
```

### Run a cloud backtest

```bash
cd /mnt/nvme_data/shared/quant_gpt
make backtest
```

### Inspect current runtime plan

```bash
cd /mnt/nvme_data/shared/quant_gpt
. .venv/bin/activate
python -m src.main provider-plan
```

### Start the first Alpaca paper deployment

Before the first deployment, validate Alpaca and select a QuantConnect live node:

```bash
cd /mnt/nvme_data/shared/quant_gpt
./scripts/check_alpaca_paper.sh
./scripts/list_qc_nodes.sh
```

Set `LEAN_CLOUD_PAPER_NODE` in `.env` to the chosen node id or node name, then deploy:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make live-paper
```

Monitor or stop the deployment from the same repo:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-status
make paper-stop
# or: make paper-liquidate
```

## Safe Defaults

For the first deployment, keep these safety properties:

- `LLM policy mode=observe_only`
- `PAPER_ENVIRONMENT=paper`
- cloud backtests enabled
- no live broker path unless you explicitly decide to use it
- no local backtest mode unless you have the required licensed data

## Common Problems

### `make verify` fails because `pytest` is missing

Re-run:

```bash
make setup
```

Or manually:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt
```

### LEAN CLI is installed but cloud commands fail

Check:

```bash
lean whoami
grep '^LEAN_ORGANIZATION_ID=' .env
grep -n '"job-organization-id"' lean_workspace/lean.json
```

The organization id must be the real QuantConnect org id, not a display name.

### LLM smoke tests fail after editing `.env`

Re-run:

```bash
make env
make llm-smoke
```

The setup script writes `.env` safely and avoids shell-parsing issues with spaced values.

## Next Docs

Use these when moving beyond quickstart:

- [docs/deployment.md](/Volumes/PiShare/quant_gpt/docs/deployment.md)
- [docs/operations.md](/Volumes/PiShare/quant_gpt/docs/operations.md)
- [docs/data-providers.md](/Volumes/PiShare/quant_gpt/docs/data-providers.md)
- [docs/llm-agent.md](/Volumes/PiShare/quant_gpt/docs/llm-agent.md)
- [docs/regression-testing.md](/Volumes/PiShare/quant_gpt/docs/regression-testing.md)
