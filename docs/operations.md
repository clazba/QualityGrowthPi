# Operations Runbook

## Default Operating Posture

Run the system in this posture unless you are intentionally changing risk:

- backtests: `cloud`
- paper deployment target: `cloud`
- paper broker: `alpaca`
- LLM mode: `observe_only`
- browser auto-open: disabled on the Pi

This gives you:

- the validated strategy path
- visible paper execution
- advisory reporting without trade influence

## Daily Operator Checklist

### Before Market Open

Run from the repo root:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make verify
make test
make paper-status
make workflow
make llm-report
```

Check:

- tests still pass
- paper deployment is still running
- the workflow report still shows a healthy opportunity set
- the LLM report is present and not broadly flagging caution or manual review across the paper basket

### During The Day

Use:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-status
make workflow
```

Check for:

- unexpected paper-status changes
- large paper position drift
- a sudden drop in target count
- LLM advisory summaries that turn broadly negative

### After Strategy Or Config Changes

Run:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make test
make e2e
make backtest
./scripts/read_backtest_diagnostics.sh <backtest_id>
```

Use this before:

- changing strategy logic
- changing provider configuration
- promoting a new baseline

### When You Want To Freeze A Good Run

```bash
cd /mnt/nvme_data/shared/quant_gpt
make baseline BACKTEST_ID=<backtest_id>
```

## How To Read The Workflow Report

The workflow report is the main operator readout.

It answers:

- is the deterministic strategy still producing candidates?
- is the current target basket healthy?
- is paper deployment aligned with expectations?
- does recent news justify caution, manual review, or no effect?

Interpretation rules:

- healthy opportunity set plus stable paper deployment means normal operating state
- collapsing target count means investigate before trusting the deployment
- `pending_prices`, `stale_data`, or empty target states mean strategy execution is impaired
- broad LLM caution or manual review means narrative risk has increased even if deterministic signals still look fine

## Backtest Review Routine

When reviewing a new backtest, check:

- `Return`
- `Net Profit`
- `Drawdown`
- `reported_total_orders`
- `closed_trade_count`
- `LastSuccessfulTargetCount`
- `LastRebalanceCheckState`

Command flow:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make backtest
./scripts/read_backtest_diagnostics.sh <backtest_id>
```

## Paper Deployment Routine

Normal commands:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-check
make paper-status
```

To stop paper:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-stop
```

Emergency liquidation:

```bash
cd /mnt/nvme_data/shared/quant_gpt
make paper-liquidate
```

## Failure Handling

### Cloud Backtest Or Paper Deploy Fails

Check:

- `lean whoami`
- `./scripts/list_qc_projects.sh`
- `./scripts/list_qc_nodes.sh`
- project id, organization id, and node settings in `.env`

### Workflow Shows No Advisories

Check:

- `make llm-report`
- `results/opportunities/llm_workflow_latest.json`
- Gemini credentials
- whether recent news was available for the current paper symbols

### Lock Problems

For runtime locks:

- inspect the owning process before removing `state/runtime.lock`

For Git locks:

- inspect running Git processes before removing `.git/index.lock`

## Preferred Diagnostics

QuantConnect cloud logs are not the primary diagnostics source for this repo.

Prefer:

- `results/backtests/cloud/<backtest_id>.json`
- `results/opportunities/trade_workflow_<timestamp>.md`
- `results/opportunities/llm_workflow_latest.json`
- `make llm-report`
