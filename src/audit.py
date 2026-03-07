"""Structured audit event helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.logging_utils import get_logger
from src.models import AuditEvent


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


class AuditLogger:
    """Dual sink audit logger for JSONL logs and optional state store persistence."""

    def __init__(self, store: Any | None = None) -> None:
        self._logger = get_logger("quant_gpt.audit")
        self._store = store

    def emit(self, event: AuditEvent) -> None:
        payload = json.dumps(event.model_dump(mode="python"), default=_json_default, sort_keys=True)
        self._logger.info(payload)
        if self._store is not None:
            self._store.record_audit_event(event)

    def order_event(self, symbol: str, status: str, quantity: float, fill_price: float | None) -> None:
        self.emit(
            AuditEvent(
                event_type="order_event",
                payload={
                    "symbol": symbol,
                    "status": status,
                    "quantity": quantity,
                    "fill_price": fill_price,
                },
            )
        )
