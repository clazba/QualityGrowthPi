"""SQLite WAL persistence for runtime state, audit logs, and advisory cache metadata."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.models import (
    AdvisoryEnvelope,
    AuditEvent,
    ClusterSnapshot,
    HoldingsSnapshot,
    MLTradeFilterDecision,
    PairCandidate,
    PairPositionState,
    PairTradeIntent,
    SentimentSnapshot,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported value for JSON serialization: {type(value)!r}")


class StateStore:
    """Repository-local SQLite state store with WAL and bounded transactions."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=10.0)
        self.connection.row_factory = sqlite3.Row
        self._apply_pragmas()

    def _apply_pragmas(self) -> None:
        # WAL keeps writers from blocking readers and is appropriate for the Pi + NVMe target.
        self.connection.execute("PRAGMA journal_mode=WAL;")
        # NORMAL reduces fsync pressure while keeping sane durability for this local runtime.
        self.connection.execute("PRAGMA synchronous=NORMAL;")
        self.connection.execute("PRAGMA foreign_keys=ON;")
        self.connection.execute("PRAGMA busy_timeout=5000;")

    def initialize(self) -> None:
        """Create required tables if they do not already exist."""

        schema = [
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS rebalance_runs (
                rebalance_key TEXT PRIMARY KEY,
                intent_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS holdings_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                source TEXT NOT NULL,
                holdings_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ts TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS provider_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                response_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentiment_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                as_of TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS advisory_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                as_of TEXT NOT NULL,
                policy_mode TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                decision_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                symbol TEXT,
                model_name TEXT NOT NULL,
                estimated_cost_usd REAL NOT NULL,
                cache_hit INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cluster_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_mode TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pair_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                pair_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                status TEXT NOT NULL,
                features_json TEXT NOT NULL,
                decision_json TEXT,
                intent_json TEXT,
                metadata_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pair_position_state (
                pair_id TEXT PRIMARY KEY,
                cluster_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
        ]
        with closing(self.connection.cursor()) as cursor:
            for statement in schema:
                cursor.execute(statement)
            cursor.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, datetime.now(UTC).isoformat()),
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def has_rebalance(self, rebalance_key: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM rebalance_runs WHERE rebalance_key = ?",
            (rebalance_key,),
        ).fetchone()
        return row is not None

    def mark_rebalance_started(
        self,
        rebalance_key: str,
        intent_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if self.has_rebalance(rebalance_key):
            return False
        self.connection.execute(
            """
            INSERT INTO rebalance_runs(rebalance_key, intent_hash, status, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rebalance_key,
                intent_hash,
                "started",
                json.dumps(metadata or {}, default=_json_default, sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()
        return True

    def mark_rebalance_completed(self, rebalance_key: str, metadata: dict[str, Any] | None = None) -> None:
        self.connection.execute(
            """
            UPDATE rebalance_runs
            SET status = ?, metadata_json = ?, completed_at = ?
            WHERE rebalance_key = ?
            """,
            (
                "completed",
                json.dumps(metadata or {}, default=_json_default, sort_keys=True),
                datetime.now(UTC).isoformat(),
                rebalance_key,
            ),
        )
        self.connection.commit()

    def save_holdings_snapshot(self, snapshot: HoldingsSnapshot) -> None:
        self.connection.execute(
            """
            INSERT INTO holdings_snapshots(as_of, source, holdings_json)
            VALUES (?, ?, ?)
            """,
            (
                snapshot.as_of.isoformat(),
                snapshot.source,
                json.dumps(snapshot.holdings, sort_keys=True),
            ),
        )
        self.connection.commit()

    def record_audit_event(self, event: AuditEvent) -> None:
        self.connection.execute(
            """
            INSERT INTO audit_events(event_type, ts, payload_json)
            VALUES (?, ?, ?)
            """,
            (
                event.event_type,
                event.ts.isoformat(),
                json.dumps(event.payload, default=_json_default, sort_keys=True),
            ),
        )
        self.connection.commit()

    def upsert_provider_cache_metadata(self, cache_key: str, provider: str, metadata: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO provider_cache(cache_key, provider, metadata_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                provider = excluded.provider,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                cache_key,
                provider,
                json.dumps(metadata, default=_json_default, sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def get_llm_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT payload_json, expires_at FROM llm_cache WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at < datetime.now(UTC):
            return None
        return json.loads(row["payload_json"])

    def put_llm_cache(
        self,
        cache_key: str,
        provider: str,
        model_name: str,
        prompt_version: str,
        response_hash: str,
        payload: dict[str, Any],
        ttl_minutes: int,
    ) -> None:
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(minutes=ttl_minutes)
        self.connection.execute(
            """
            INSERT INTO llm_cache(
                cache_key, provider, model_name, prompt_version, response_hash, payload_json, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                provider = excluded.provider,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                response_hash = excluded.response_hash,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (
                cache_key,
                provider,
                model_name,
                prompt_version,
                response_hash,
                json.dumps(payload, default=_json_default, sort_keys=True),
                created_at.isoformat(),
                expires_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_sentiment_snapshot(self, snapshot: SentimentSnapshot) -> None:
        self.connection.execute(
            """
            INSERT INTO sentiment_snapshots(symbol, as_of, payload_json)
            VALUES (?, ?, ?)
            """,
            (
                snapshot.symbol,
                snapshot.as_of.isoformat(),
                snapshot.model_dump_json(),
            ),
        )
        self.connection.commit()

    def save_advisory_envelope(self, envelope: AdvisoryEnvelope, policy_mode: str) -> None:
        self.connection.execute(
            """
            INSERT INTO advisory_history(symbol, as_of, policy_mode, payload_json, decision_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                envelope.advisory.symbol,
                envelope.as_of.isoformat(),
                policy_mode,
                envelope.advisory.model_dump_json(),
                envelope.decision.model_dump_json(),
            ),
        )
        self.connection.commit()

    def latest_advisories(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT symbol, as_of, policy_mode, payload_json, decision_json
            FROM advisory_history
            ORDER BY as_of DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "symbol": row["symbol"],
                "as_of": row["as_of"],
                "policy_mode": row["policy_mode"],
                "payload": json.loads(row["payload_json"]),
                "decision": json.loads(row["decision_json"]),
            }
            for row in rows
        ]

    def save_cluster_snapshots(
        self,
        snapshots: list[ClusterSnapshot],
        strategy_mode: str = "stat_arb_graph_pairs",
    ) -> None:
        self.connection.executemany(
            """
            INSERT INTO cluster_snapshots(strategy_mode, cluster_id, as_of, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    strategy_mode,
                    snapshot.cluster_id,
                    snapshot.as_of.isoformat(),
                    snapshot.model_dump_json(),
                )
                for snapshot in snapshots
            ],
        )
        self.connection.commit()

    def save_pair_opportunity(
        self,
        as_of: datetime,
        candidate: PairCandidate,
        status: str,
        decision: MLTradeFilterDecision | None = None,
        intent: PairTradeIntent | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO pair_opportunities(
                as_of, pair_id, cluster_id, status, features_json, decision_json, intent_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                as_of.isoformat(),
                candidate.pair_id,
                candidate.cluster_id,
                status,
                candidate.spread_features.model_dump_json(),
                None if decision is None else decision.model_dump_json(),
                None if intent is None else intent.model_dump_json(),
                json.dumps(metadata or candidate.metadata, default=_json_default, sort_keys=True),
            ),
        )
        self.connection.commit()

    def upsert_pair_position_state(self, state: PairPositionState) -> None:
        self.connection.execute(
            """
            INSERT INTO pair_position_state(pair_id, cluster_id, status, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(pair_id) DO UPDATE SET
                cluster_id = excluded.cluster_id,
                status = excluded.status,
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
            """,
            (
                state.pair_id,
                state.cluster_id,
                state.status,
                state.updated_at.isoformat(),
                state.model_dump_json(),
            ),
        )
        self.connection.commit()

    def latest_cluster_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT strategy_mode, cluster_id, as_of, payload_json
            FROM cluster_snapshots
            ORDER BY as_of DESC, cluster_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "strategy_mode": row["strategy_mode"],
                "cluster_id": row["cluster_id"],
                "as_of": row["as_of"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def latest_pair_opportunities(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT as_of, pair_id, cluster_id, status, features_json, decision_json, intent_json, metadata_json
            FROM pair_opportunities
            ORDER BY as_of DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "as_of": row["as_of"],
                "pair_id": row["pair_id"],
                "cluster_id": row["cluster_id"],
                "status": row["status"],
                "features": json.loads(row["features_json"]),
                "decision": None if row["decision_json"] is None else json.loads(row["decision_json"]),
                "intent": None if row["intent_json"] is None else json.loads(row["intent_json"]),
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def open_pair_positions(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT pair_id, cluster_id, status, updated_at, payload_json
            FROM pair_position_state
            WHERE status = 'open'
            ORDER BY updated_at DESC, pair_id ASC
            """
        ).fetchall()
        return [
            {
                "pair_id": row["pair_id"],
                "cluster_id": row["cluster_id"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def record_llm_usage(
        self,
        model_name: str,
        symbol: str | None,
        estimated_cost_usd: float,
        cache_hit: bool,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO llm_usage(recorded_at, symbol, model_name, estimated_cost_usd, cache_hit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                symbol,
                model_name,
                estimated_cost_usd,
                int(cache_hit),
            ),
        )
        self.connection.commit()

    def daily_llm_spend(self, day: datetime | None = None) -> float:
        reference = day or datetime.now(UTC)
        start = datetime.combine(reference.date(), datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS total_cost
            FROM llm_usage
            WHERE recorded_at >= ? AND recorded_at < ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return float(row["total_cost"]) if row is not None else 0.0

    def prune_expired_llm_cache(self) -> int:
        cursor = self.connection.execute(
            "DELETE FROM llm_cache WHERE expires_at < ?",
            (datetime.now(UTC).isoformat(),),
        )
        self.connection.commit()
        return int(cursor.rowcount or 0)
