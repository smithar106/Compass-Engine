"""Claiming: the enrichment work queue.

A ``CandidateProvider`` lists documents/records that need enrichment. The
``ClaimQueue`` acquires exclusive claims via ``AgentStore`` so multiple worker
processes never process the same candidate twice.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from compass_agent.store import AgentStore


class CandidateProvider:
    """Base class: yields candidates as dicts with keys
    ``id``, ``record_id``, ``doc_id``, ``source``, ``text``, ``title``."""

    def list_candidates(self, limit: int, exclude_ids: Optional[set] = None) -> "list[dict]":
        raise NotImplementedError


class CollectorCandidateProvider(CandidateProvider):
    """Candidates from a Compass collector SQLite database.

    Targets intervention records that need enrichment: thin/not-yet-rich
    records, or rich records still missing organization dimensions (employee
    count or geography) that the LLM enrichment can backfill.
    """

    def __init__(self, db_path: str, min_text_chars: int = 120) -> None:
        self.db_path = db_path
        self.min_text_chars = min_text_chars

    def list_candidates(self, limit: int, exclude_ids: Optional[set] = None) -> "list[dict]":
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except (sqlite3.Error, OSError):
            return []
        try:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("SELECT COUNT(*) FROM intervention_records")
            except sqlite3.Error:
                return []

            exclude_ids = exclude_ids or set()
            params: list = []
            where_extra = ""
            if exclude_ids:
                placeholders = ", ".join("?" for _ in exclude_ids)
                where_extra = f" AND r.id NOT IN ({placeholders})"
                params.extend(sorted(exclude_ids))

            sql = (
                """
                SELECT r.id AS record_id,
                       r.document_id AS doc_id,
                       r.source_id AS source,
                       r.problem_statement AS problem,
                       r.intervention_title AS intervention,
                       d.cleaned_text AS text,
                       d.title AS title
                FROM intervention_records r
                LEFT JOIN documents d ON d.id = r.document_id
                WHERE (
                        (r.implementation_richness IS NULL
                         OR r.implementation_richness IN ('thin','usable'))
                        OR r.organization_employee_count IS NULL
                        OR r.organization_geography IS NULL
                        OR r.organization_geography = '[]'
                      )
                  AND (COALESCE(r.implementation_field_provenance,'[]') = '[]'
                       OR r.implementation_field_provenance IS NULL)
                """
                + where_extra
                + " ORDER BY r.created_at ASC LIMIT ?"
            )
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

            candidates = []
            for r in rows:
                text = r["text"] or r["problem"] or r["intervention"] or ""
                if len(str(text).strip()) < self.min_text_chars:
                    continue
                candidates.append(
                    {
                        "id": r["record_id"],
                        "record_id": r["record_id"],
                        "doc_id": r["doc_id"] or "",
                        "source": r["source"] or "",
                        "text": str(text),
                        "title": r["title"] or "",
                    }
                )
            return candidates
        finally:
            conn.close()


class ClaimQueue:
    """Acquires exclusive claims and tracks completion through the store."""

    def __init__(self, provider: CandidateProvider, store: AgentStore, owner: str = "daemon") -> None:
        self.provider = provider
        self.store = store
        self.owner = owner

    def next_batch(self, limit: int) -> "list[dict]":
        # Exclude already-claimed candidates in SQL so we don't stall scanning
        # the same oldest records every cycle.
        claimed = self.store.claimed_ids()
        candidates = self.provider.list_candidates(limit, exclude_ids=claimed)
        acquired = []
        for c in candidates:
            if len(acquired) >= limit:
                break
            if self.store.claim(c, owner=self.owner):
                acquired.append(c)
        return acquired

    def complete(self, candidate_id: str, status: str = "done") -> None:
        self.store.mark(candidate_id, status)
