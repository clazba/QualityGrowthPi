"""Local control-plane entrypoint for the quant stack."""

from __future__ import annotations

import argparse
import json
import signal
from datetime import UTC, datetime

from src.audit import AuditLogger
from src.health import RuntimeLock, build_startup_banner, emit_heartbeat
from src.logging_utils import configure_logging, get_logger
from src.models import AuditEvent
from src.provider_adapters.factory import resolve_provider_plan
from src.settings import load_settings
from src.state_store import StateStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quant trading control plane")
    subparsers = parser.add_subparsers(dest="command", required=False)
    subparsers.add_parser("health", help="Initialize logging and emit a heartbeat")
    subparsers.add_parser("init-db", help="Initialize the SQLite state store")
    subparsers.add_parser("llm-report", help="Print the latest advisory decisions")
    subparsers.add_parser("provider-plan", help="Print the resolved backtest/paper/local provider plan")
    return parser


def _print_llm_report(store: StateStore) -> None:
    report = store.latest_advisories(limit=10)
    print(json.dumps(report, indent=2, sort_keys=True))


def _print_provider_plan(settings) -> None:
    print(json.dumps(resolve_provider_plan(settings).as_dict(), indent=2, sort_keys=True))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings)
    logger = get_logger("quant_gpt")
    store = StateStore(settings.state_db_path)
    store.initialize()
    audit = AuditLogger(store=store)

    command = args.command or "health"
    if command == "init-db":
        logger.info("Initialized database at %s", settings.state_db_path)
        store.close()
        return 0

    if command == "llm-report":
        _print_llm_report(store)
        store.close()
        return 0

    if command == "provider-plan":
        _print_provider_plan(settings)
        store.close()
        return 0

    def _handle_signal(signum, _frame) -> None:
        logger.warning("Shutdown signal received signum=%s", signum)
        store.close()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    with RuntimeLock(settings.lock_path):
        logger.info(build_startup_banner(settings))
        pruned = store.prune_expired_llm_cache()
        logger.info("Pruned expired llm cache entries=%s", pruned)
        emit_heartbeat(settings)
        audit.emit(
            AuditEvent(
                event_type="startup",
                payload={
                    "command": command,
                    "state_db": str(settings.state_db_path),
                    "runtime_root": str(settings.runtime_root),
                    "provider_plan": resolve_provider_plan(settings).as_dict(),
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
        )
        logger.info("Health command completed")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
