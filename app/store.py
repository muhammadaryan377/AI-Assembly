from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    condition_signature TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    source_quote TEXT NOT NULL,
                    expert TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conflicts (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    rule_a_id TEXT NOT NULL,
                    rule_b_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolution TEXT NOT NULL DEFAULT '',
                    differentiating_condition TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_rules_topic ON rules(topic);
                CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status);
                """
            )

    def add_rule(
        self,
        *,
        topic: str,
        conditions: dict[str, Any],
        condition_signature: str,
        action: str,
        rationale: str,
        source_quote: str,
        expert: str,
        confidence: float,
    ) -> dict[str, Any]:
        rule_id = f"KR-{uuid.uuid4().hex[:8].upper()}"
        created_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rules (
                    id, topic, conditions_json, condition_signature, action,
                    rationale, source_quote, expert, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    topic,
                    json.dumps(conditions, sort_keys=True),
                    condition_signature,
                    action,
                    rationale,
                    source_quote,
                    expert,
                    confidence,
                    created_at,
                ),
            )
        return {
            "id": rule_id,
            "topic": topic,
            "conditions": conditions,
            "action": action,
            "rationale": rationale,
            "source_quote": source_quote,
            "expert": expert,
            "confidence": confidence,
            "created_at": created_at,
        }

    def list_rules(self, topic: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM rules"
        params: tuple[Any, ...] = ()
        if topic:
            query += " WHERE lower(topic) = lower(?)"
            params = (topic,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def find_same_signature(self, topic: str, signature: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rules
                WHERE lower(topic) = lower(?) AND condition_signature = ?
                ORDER BY created_at DESC
                """,
                (topic, signature),
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def add_conflict(
        self,
        *,
        topic: str,
        rule_a_id: str,
        rule_b_id: str,
        reason: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM conflicts
                WHERE status = 'open'
                  AND ((rule_a_id = ? AND rule_b_id = ?) OR (rule_a_id = ? AND rule_b_id = ?))
                LIMIT 1
                """,
                (rule_a_id, rule_b_id, rule_b_id, rule_a_id),
            ).fetchone()
            if existing:
                return dict(existing)

            conflict_id = f"CF-{uuid.uuid4().hex[:8].upper()}"
            created_at = utc_now()
            conn.execute(
                """
                INSERT INTO conflicts (
                    id, topic, rule_a_id, rule_b_id, reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (conflict_id, topic, rule_a_id, rule_b_id, reason, created_at),
            )
        return {
            "id": conflict_id,
            "topic": topic,
            "rule_a_id": rule_a_id,
            "rule_b_id": rule_b_id,
            "reason": reason,
            "status": "open",
            "created_at": created_at,
        }

    def list_conflicts(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM conflicts"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution: str,
        differentiating_condition: str = "",
    ) -> dict[str, Any] | None:
        resolved_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE conflicts
                SET status = 'resolved', resolution = ?, differentiating_condition = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolution, differentiating_condition, resolved_at, conflict_id),
            )
            row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
        return dict(row) if row else None

    def add_audit(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    f"AU-{uuid.uuid4().hex[:10].upper()}",
                    event_type,
                    json.dumps(payload, sort_keys=True),
                    utc_now(),
                ),
            )

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rules = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            open_conflicts = conn.execute(
                "SELECT COUNT(*) FROM conflicts WHERE status = 'open'"
            ).fetchone()[0]
            experts = conn.execute(
                "SELECT COUNT(DISTINCT expert) FROM rules"
            ).fetchone()[0]
            topics = conn.execute(
                "SELECT COUNT(DISTINCT lower(topic)) FROM rules"
            ).fetchone()[0]
        return {
            "rules": rules,
            "open_conflicts": open_conflicts,
            "experts": experts,
            "topics": topics,
        }

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["conditions"] = json.loads(item.pop("conditions_json"))
        item.pop("condition_signature", None)
        return item
