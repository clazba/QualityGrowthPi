# Operations Runbook

## Default Mode

Initial deployment should run in:

- provider mode: `paper`
- LLM mode: `observe_only`
- logging level: `DEBUG`

This preserves auditability while preventing the advisory subsystem from affecting orders.

## Startup Sequence

1. Validate host dependencies with `make verify`
2. Confirm `.env` exists with correct file permissions
3. Confirm the SQLite database is reachable
4. Check that the runtime lock is not already held
5. Start backtest or paper trading mode
6. Inspect `logs/app.log`, `logs/audit.jsonl`, and `logs/llm.log`

## Rebalance Safety

The runtime stores a rebalance key per month and strategy instance. On restart:

- if the key already exists and completed successfully, the rebalance is skipped
- if a prior attempt was interrupted, the operator can review the persisted intent hash and audit log before retry

## Failure Handling

### LLM Failure

Expected behaviour:

- advisory request timeout or validation failure is logged
- deterministic strategy continues unchanged
- policy gate returns `no_effect`

### Provider Failure

Expected behaviour:

- stale data checks block rebalance if required market data is missing
- provider adapter emits structured error context
- operator review is required before enabling live mode again

### Duplicate Launch

The process lock under `state/runtime.lock` prevents concurrent local runs. Remove it only after confirming the owning process is gone.

## Audit Review

Critical audit artefacts:

- rebalance key
- selected symbols
- fundamental and timing scores
- target weights
- order events
- advisory payloads and downstream policy effects

## Recovery Procedure

1. Stop the active process
2. Inspect recent logs
3. Review last rebalance record in SQLite
4. Confirm data freshness and provider health
5. Re-run smoke tests if the failure involved configuration drift
6. Restart in paper mode first if the incident touched execution or provider credentials
