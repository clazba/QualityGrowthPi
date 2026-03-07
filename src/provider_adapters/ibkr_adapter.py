"""Interactive Brokers execution adapter scaffold."""

from __future__ import annotations

from typing import Any

from src.provider_adapters.base import ExecutionProvider, ProviderError


class IBKRExecutionAdapter(ExecutionProvider):
    """Execution adapter placeholder with explicit paper/live safety boundaries."""

    def __init__(self, host: str, port: int, account: str, client_id: int) -> None:
        self.host = host
        self.port = port
        self.account = account
        self.client_id = client_id

    def provider_name(self) -> str:
        return "ibkr"

    def validate(self, paper: bool = True) -> None:
        if not self.account:
            raise ProviderError("IBKR_ACCOUNT is not configured")
        if paper and self.port not in {7497, 4002}:
            raise ProviderError("Expected a paper-trading port for IBKR paper mode")

    def submit_target_weights(self, targets: dict[str, float], paper: bool = True) -> dict[str, Any]:
        self.validate(paper=paper)
        raise ProviderError(
            "IBKR order submission is intentionally not enabled in the scaffold. "
            "Wire this adapter to a supported local IBKR client library only after paper trading procedures, "
            "recovery controls, and regression validation are complete."
        )
