# Security Notes

## Secrets

- secrets live in `.env` only
- `.env` is created with permission `600`
- no credentials are committed to version control

## Execution Safety

- live broker mode requires explicit operator confirmation
- LLM never places orders
- runtime locks prevent duplicate launches
- configuration is environment driven, not edited inline in scripts

## Data Handling

- prompt and response caches may contain sensitive market context; keep them on local NVMe storage
- logs should not include raw secrets
- provider adapters should redact credentials from exceptions

## Operator Guidance

- rotate API keys if they are ever printed or mishandled
- keep the Pi updated with security patches
- do not expose SQLite, logs, or `.env` over insecure shares
