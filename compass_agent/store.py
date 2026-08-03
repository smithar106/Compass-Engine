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
CREATE TABLE IF NOT EXISTS campaigns (
    id                     TEXT PRIMARY KEY,
    workflow               TEXT NOT NULL,
    business_function      TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'planned',
    target_fields          TEXT NOT NULL DEFAULT '[]',
    source_types           TEXT NOT NULL DEFAULT '[]',
    estimated_records_needed INTEGER NOT NULL DEFAULT 0,
    expected_impact        REAL NOT NULL DEFAULT 0,
    discovered             INTEGER NOT NULL DEFAULT 0,
    accepted               INTEGER NOT NULL DEFAULT 0,
    rejected               INTEGER NOT NULL DEFAULT 0,
    rich_records_created   INTEGER NOT NULL DEFAULT 0,
    cost_usd               REAL NOT NULL DEFAULT 0,
    benchmark_before       REAL NOT NULL DEFAULT 0,
    benchmark_after        REAL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS libraries (
    id                     TEXT PRIMARY KEY,
    name                   TEXT NOT NULL,
    category               TEXT NOT NULL DEFAULT '',
    entry_urls             TEXT NOT NULL DEFAULT '[]',
    estimated_quality      REAL NOT NULL DEFAULT 0.5,
    discovered             INTEGER NOT NULL DEFAULT 0,
    processed              INTEGER NOT NULL DEFAULT 0,
    accepted               INTEGER NOT NULL DEFAULT 0,
    rejected               INTEGER NOT NULL DEFAULT 0,
    remaining              INTEGER NOT NULL DEFAULT 0,
    cost_usd               REAL NOT NULL DEFAULT 0,
    acceptance_rate        REAL NOT NULL DEFAULT 0,
    avg_implementation_fields REAL NOT NULL DEFAULT 0,
    benchmark_contribution REAL NOT NULL DEFAULT 0,
    last_crawl             TEXT,
    next_crawl             TEXT,
    acquisition            TEXT NOT NULL DEFAULT '{}',
    acquisition_stats      TEXT NOT NULL DEFAULT '{}',
    api_urls               TEXT NOT NULL DEFAULT '[]',
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_pages (
    url            TEXT PRIMARY KEY,
    library_id     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'discovered',
    title          TEXT DEFAULT '',
    content_hash   TEXT DEFAULT '',
    accepted_record TEXT DEFAULT '',
    processed_at   TEXT
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
        # lightweight migration for existing stores (additive columns)
        for column, decl in (
            ("acquisition", "TEXT NOT NULL DEFAULT '{}'"),
            ("acquisition_stats", "TEXT NOT NULL DEFAULT '{}'"),
            ("api_urls", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE libraries ADD COLUMN {column} {decl}")
            except sqlite3.OperationalError:
                pass  # column already exists
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

    # -- campaigns ---------------------------------------------------------
    def save_campaign(self, campaign: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO campaigns (id, workflow, business_function,"
                " status, target_fields, source_types, estimated_records_needed,"
                " expected_impact, discovered, accepted, rejected,"
                " rich_records_created, cost_usd, benchmark_before, benchmark_after,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    campaign["id"],
                    campaign["workflow"],
                    campaign["business_function"],
                    campaign["status"],
                    json.dumps(campaign.get("target_fields", [])),
                    json.dumps(campaign.get("source_types", [])),
                    campaign.get("estimated_records_needed", 0),
                    campaign.get("expected_impact", 0.0),
                    campaign.get("discovered", 0),
                    campaign.get("accepted", 0),
                    campaign.get("rejected", 0),
                    campaign.get("rich_records_created", 0),
                    campaign.get("cost_usd", 0.0),
                    campaign.get("benchmark_before", 0.0),
                    campaign.get("benchmark_after"),
                    campaign.get("created_at") or _now(),
                    campaign.get("updated_at") or _now(),
                ),
            )

    def list_campaigns(self, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM campaigns WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["target_fields"] = json.loads(data["target_fields"] or "[]")
            data["source_types"] = json.loads(data["source_types"] or "[]")
            out.append(data)
        return out

    def update_campaign(self, campaign_id: str, **fields) -> None:
        if not fields:
            return
        fields = {k: v for k, v in fields.items()}
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE campaigns SET {assignments} WHERE id = ?",
                (*fields.values(), campaign_id),
            )

    # -- libraries ---------------------------------------------------------
    def save_library(self, library: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO libraries (id, name, category, entry_urls,"
                " estimated_quality, discovered, processed, accepted, rejected,"
                " remaining, cost_usd, acceptance_rate, avg_implementation_fields,"
                " benchmark_contribution, last_crawl, next_crawl, acquisition,"
                " acquisition_stats, api_urls, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    library["id"], library["name"], library.get("category", ""),
                    json.dumps(library.get("entry_urls", [])),
                    library.get("estimated_quality", 0.5),
                    library.get("discovered", 0), library.get("processed", 0),
                    library.get("accepted", 0), library.get("rejected", 0),
                    library.get("remaining", 0), library.get("cost_usd", 0.0),
                    library.get("acceptance_rate", 0.0),
                    library.get("avg_implementation_fields", 0.0),
                    library.get("benchmark_contribution", 0.0),
                    library.get("last_crawl"), library.get("next_crawl"),
                    json.dumps(library.get("acquisition") or {}),
                    json.dumps(library.get("acquisition_stats") or {}),
                    json.dumps(library.get("api_urls", [])),
                    library.get("created_at") or _now(), library.get("updated_at") or _now(),
                ),
            )

    def list_libraries(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM libraries ORDER BY name").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["entry_urls"] = json.loads(data["entry_urls"] or "[]")
            data["api_urls"] = json.loads(data["api_urls"] or "[]")
            data["acquisition"] = json.loads(data["acquisition"] or "{}")
            data["acquisition_stats"] = json.loads(data["acquisition_stats"] or "{}")
            out.append(data)
        return out

    def update_library(self, library_id: str, **fields) -> None:
        if not fields:
            return
        fields = {k: v for k, v in fields.items()}
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE libraries SET {assignments} WHERE id = ?",
                (*fields.values(), library_id),
            )

    def claim_library_page(self, url: str, library_id: str, title: str = "") -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT OR IGNORE INTO library_pages (url, library_id, status, title)"
                    " VALUES (?,?,?,?)",
                    (url, library_id, "discovered", title),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def pending_library_pages(self, library_id: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT url, title FROM library_pages WHERE library_id = ? AND status = 'discovered'"
            " ORDER BY processed_at IS NULL DESC, url LIMIT ?",
            (library_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_library_page(self, url: str, status: str, accepted_record: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE library_pages SET status = ?, accepted_record = ?, processed_at = ? WHERE url = ?",
                (status, accepted_record, _now(), url),
            )

    def library_page_status(self, url: str) -> str:
        row = self.conn.execute(
            "SELECT status FROM library_pages WHERE url = ?", (url,)
        ).fetchone()
        return row[0] if row else "discovered"


def format_budget_state(budget) -> dict:
    """Snapshot budget + store state for cycle reports (no secrets)."""
    return {
        "daily_spent": round(budget.daily_spent, 6),
        "max_daily": budget.max_daily,
        "total_spent": round(budget.total_spent, 6),
        "max_total": budget.max_total,
    }
