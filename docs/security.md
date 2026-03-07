# Security

## Secrets Handling

All credentials should live in `.env` only.

Examples:

- QuantConnect user id and API token
- Alpaca API key and secret
- Gemini API key
- Massive API key
- Alpha Vantage API key

Rules:

- never commit `.env`
- do not paste secrets into docs or code
- keep `.env` permission-restricted
- rotate credentials if you suspect exposure

## Trust Boundaries

This repo has two main trust boundaries:

- QuantConnect cloud for backtests and paper deployment
- the local Pi runtime for operator reporting, validation, and workflow orchestration

Be clear about what crosses the boundary:

- LEAN project code is synced to QuantConnect for cloud runs
- Alpaca credentials are used for the paper deployment path
- local workflow artefacts remain under the runtime root unless you explicitly move them

## LLM Safety

The LLM subsystem is intentionally constrained.

Safety properties:

- it never places orders directly
- default mode is `observe_only`
- malformed outputs fail open
- advisory decisions are stored for review
- bounded risk policy exists but is not the default operating mode

## Local Data Safety

Sensitive artefacts may exist under:

- `state/`
- `logs/`
- `results/`
- `data/`

These may contain:

- prompt and response cache entries
- advisory history
- paper position snapshots
- backtest diagnostics

Do not expose these directories over insecure file sharing or casual remote access.

## Operational Safety Practices

- run paper trading before considering any live path
- keep `PAPER_ENVIRONMENT=paper` unless you intentionally promote the workflow
- require explicit operator confirmation for deploy and stop actions
- inspect `make workflow` and `make llm-report` before trusting the current state
- treat workflow reports and saved diagnostics as internal operational data

## Host Guidance

- keep both the Pi and the Mac updated
- avoid running as root unless necessary
- verify stale lock files before deleting them
- prefer the provided scripts over ad hoc command variants for broker, LEAN, or workflow operations

## Logging Guidance

- logs should contain context, not secrets
- if a provider error accidentally prints a secret, rotate it
- saved backtest diagnostics and advisory outputs should be treated as internal records
