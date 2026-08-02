"""SQLite-backed state store for the Compass Evidence Agent.

Holds claims (the work queue), enrichment results, and benchmark runs.
Uses only the standard library. Persistence is optional: pass ``AGENT_DB_PATH``
to keep state across restarts (a Railway volume is *not* required — without a
path the store is in-memory).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    candidate_id   TEXT PRIMARY KEY,
    claimed_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'claimed',  -- claimed|done|failed|skipped
    owner          TEXT NOT NULL DEFAULT '',
    attempts       INTEGER NOT NULL DEFAULT 1,
    record_id      TEXT DEFAULT '',
    doc_id         TEXT DEFAULT '',
    source         TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS enrichment_results (
    id            TEXT PRIMARY KEY,
    candidate_id  TEXT NOT NULL,
    record_id     TEXT DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '{}',
    validation    TEXT NOT NULL DEFAULT '{}',
    valid         INTEGER NOT NULL DEFAULT 0,
    cost          REAL NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    model         TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    report     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentStore:
    """Claims + enrichment + benchmark persistence. Thread-safe enough for the
    worker's bounded concurrency (serialized via the sqlite3 connection lock)."""

    def __init__(self, db_path: str = "") -> None:
        self.db_path = db_path or ""
        self.conn = sqlite3.connect(self.db_path or ":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- claiming ----------------------------------------------------------
    def claim(self, candidate: dict, owner: str = "daemon") -> bool:
        """Atomically claim a candidate. Returns True if this call acquired it."""
        candidate_id = candidate["id"]
        record_id = candidate.get("record_id", "")
        doc_id = candidate.get("doc_id", "")
        source = candidate.get("source", "")
        with self.conn:
            cur = self.conn.execute(
                "SELECT 1 FROM claims WHERE candidate_id = ?",
                (candidate_id,),
            )
            if cur.fetchone():
                return False
            self.conn.execute(
                "INSERT INTO claims (candidate_id, claimed_at, status, owner,"
                " attempts, record_id, doc_id, source) VALUES (?,?,?,?,?,?,?,?)",
                (candidate_id, _now(), "claimed", owner, 1, record_id, doc_id, source),
            )
        return True

    def claimed_ids(self) -> "set[str]":
        cur = self.conn.execute("SELECT candidate_id FROM claims")
        return {r["candidate_id"] for r in cur.fetchall()}

    def mark(self, candidate_id: str, status: str, attempts: Optional[int] = None) -> None:
        if status not in ("claimed", "done", "failed", "skipped"):
            raise ValueError(f"invalid claim status: {status}")
        with self.conn:
            if attempts is None:
                self.conn.execute(
                    "UPDATE claims SET status = ? WHERE candidate_id = ?",
                    (status, candidate_id),
                )
            else:
                self.conn.execute(
                    "UPDATE claims SET status = ?, attempts = ? WHERE candidate_id = ?",
                    (status, attempts, candidate_id),
                )
        self.conn.commit()

    # -- enrichment results ------------------------------------------------
    def save_result(
        self,
        candidate_id: str,
        payload: dict,
        validation: dict,
        valid: bool,
        cost: float,
        input_tokens: int,
        output_tokens: int,
        model: str,
        record_id: str = "",
    ) -> str:
        result_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO enrichment_results (id, candidate_id, record_id,"
                " payload, validation, valid, cost, input_tokens, output_tokens,"
                " model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result_id,
                    candidate_id,
                    record_id,
                    json.dumps(payload),
                    json.dumps(validation),
                    1 if valid else 0,
                    float(cost),
                    int(input_tokens),
                    int(output_tokens),
                    model,
                    _now(),
                ),
            )
        return result_id

    def latest_result(self, candidate_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM enrichment_results WHERE candidate_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data["payload"] or "{}")
        data["validation"] = json.loads(data["validation"] or "{}")
        data["valid"] = bool(data["valid"])
        return data

    # -- benchmarks --------------------------------------------------------
    def save_benchmark(self, kind: str, report: dict) -> str:
        run_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO benchmark_runs (id, kind, report, created_at)"
                " VALUES (?,?,?,?)",
                (run_id, kind, json.dumps(report), _now()),
            )
        return run_id

    def recent_benchmarks(self, limit: int = 5) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM benchmark_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        out = []
        for row in cur.fetchall():
            data = dict(row)
            data["report"] = json.loads(data["report"] or "{}")
            out.append(data)
        return out


def format_budget_state(budget) -> dict:
    """Snapshot budget + store state for cycle reports (no secrets)."""
    return {
        "daily_spent": round(budget.daily_spent, 6),
        "max_daily": budget.max_daily,
        "total_spent": round(budget.total_spent, 6),
        "max_total": budget.max_total,
    }
