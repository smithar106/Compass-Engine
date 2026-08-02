"""Auto-publish: write validated enrichment back to the collector database.

Only writes when auto-publish is enabled and a collector DB path is known.
Otherwise it logs what *would* have been written.

Beyond the Implementation Intelligence fields, publishing backfills the
organization dimensions needed for context-aware retrieval: employee count
(and band) from the LLM extraction, and geography inferred deterministically
from the source text when not already present.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3

log = logging.getLogger("compass_agent.publish")

_GEO_PATTERNS = [
    (r"\b(?:based|headquartered|headquarters) in ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", 0.8),
    (r"\b(U\.S\.|USA|United States|UK|Germany|Canada|Japan|Australia|India|China|Singapore|Brazil|Netherlands|Sweden|Switzerland|France|Spain|Italy)\b", 0.7),
]
_COUNTRY_MAP = {
    "us": "United States", "usa": "United States", "u.s.": "United States",
    "united states": "United States", "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
}
_EMP_PATTERNS = [
    r"(\d[\d,]*)\s*(?:employees|people|staff|ftes)",
    r"(?:more than|over|>|~|around)\s*(\d[\d,]*)\s*employees",
]


def _infer_geography(text: str) -> str:
    if not text:
        return ""
    for pattern, _conf in _GEO_PATTERNS:
        m = re.search(pattern, text)
        if m:
            candidate = m.group(1).strip()
            key = candidate.lower()
            return _COUNTRY_MAP.get(key, candidate)
    return ""


def _infer_employee_count(text: str) -> int | None:
    if not text:
        return None
    for pattern in _EMP_PATTERNS:
        m = re.search(pattern, text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _employee_count_to_band(count) -> str:
    if count is None:
        return ""
    if count < 10:
        return "<10"
    if count < 50:
        return "10-50"
    if count < 200:
        return "50-200"
    if count < 1000:
        return "200-1000"
    if count < 10000:
        return "1000-10000"
    return "10000+"


def build_enrichment_fields(payload: dict, source_text: str = "") -> dict:
    """Map a validated enrichment payload onto collector-DB columns."""
    components = {
        "workflow": payload.get("workflow", ""),
        "intervention_category": payload.get("intervention_category", ""),
        "evidence_tier": str(payload.get("evidence_tier") or "").lower(),
        "source_generation": "agent_enriched",
    }
    fields = {
        "intervention_title": payload.get("intervention_title", ""),
        "intervention_description": payload.get("result_summary", ""),
        "intervention_vendors": payload.get("intervention_vendors") or [],
        "intervention_components": components,
        "implementation_partner": payload.get("implementation_partner") or [],
        "implementation_pattern": payload.get("implementation_pattern") or [],
        "lessons_learned": payload.get("lessons_learned") or [],
        "change_management": payload.get("change_management", ""),
        "rollout_strategy": payload.get("rollout_strategy", ""),
        "governance_model": payload.get("governance_model", ""),
        "executive_sponsor": payload.get("executive_sponsor", ""),
        "pilot_structure": payload.get("pilot_structure", ""),
        "training_approach": payload.get("training_approach", ""),
        "adoption_approach": payload.get("adoption_approach", ""),
        "implementation_team_structure": payload.get("implementation_team_structure", ""),
        "budget_range": payload.get("budget_range", ""),
        "key_decision_makers": payload.get("key_decision_makers") or [],
        "success_criteria": payload.get("success_criteria") or [],
        "implementation_richness": "rich",
        "review_status": "agent_enriched",
    }

    # Organization dimensions backfill (employee + geography).
    employee_count = payload.get("organization_employee_count")
    if employee_count is None and source_text:
        employee_count = _infer_employee_count(source_text)
    if employee_count not in (None, 0, ""):
        fields["organization_employee_count"] = int(employee_count)
        fields["organization_employee_band"] = _employee_count_to_band(int(employee_count))

    geography = payload.get("organization_geography") or payload.get("headquarters_country") or ""
    if isinstance(geography, list):
        geography = next((g for g in geography if g), "")
    if not geography and source_text:
        geography = _infer_geography(source_text)
    if geography:
        fields["organization_geography"] = [str(geography)]

    return fields


class Publisher:
    """Writes validated enrichment back to a collector SQLite database."""

    def __init__(self, db_path: str = "", enabled: bool = False) -> None:
        self.db_path = db_path
        self.enabled = enabled

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.db_path)

    def publish(self, record_id: str, payload: dict, source_text: str = "") -> int:
        """Update one intervention record. Returns number of rows updated."""
        if not self.active or not record_id:
            return 0
        fields = build_enrichment_fields(payload, source_text)
        try:
            conn = sqlite3.connect(self.db_path)
            # WAL lets the engine read the shared DB without writer lockouts.
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
        except sqlite3.Error as exc:
            log.warning("Cannot open collector DB for publish: %s", exc)
            return 0
        try:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            values = [_jsonify(v) for v in fields.values()]
            conn.execute(
                f"UPDATE intervention_records SET {assignments} WHERE id = ?",
                (*values, record_id),
            )
            conn.commit()
            return conn.total_changes
        except sqlite3.Error as exc:
            log.warning("Publish failed for %s: %s", record_id, exc)
            return 0
        finally:
            conn.close()


def _jsonify(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value)


class HttpPublisher:
    """Publishes validated enrichment to the engine over HTTP (Phase 5 sync).

    The engine's ``POST /api/evidence/enrichment`` endpoint upserts the fields
    onto its own evidence database, so enrichment results reach engine retrieval
    without requiring a shared filesystem.
    """

    def __init__(self, api_url: str = "", token: str = "", enabled: bool = False) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.enabled = enabled

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.api_url) and bool(self.token)

    def publish(self, record_id: str, payload: dict, source_text: str = "") -> int:
        if not self.active or not record_id:
            return 0
        import httpx

        fields = build_enrichment_fields(payload, source_text)
        try:
            resp = httpx.post(
                f"{self.api_url}/api/evidence/enrichment",
                headers={"X-Compass-Agent-Key": self.token},
                json={"record_id": record_id, "fields": fields, "source": "compass_agent"},
                timeout=30,
            )
            if resp.status_code == 200:
                return 1
            log.warning(
                "Engine publish for %s returned %s: %s",
                record_id,
                resp.status_code,
                resp.text[:200],
            )
            return 0
        except Exception as exc:
            log.warning("Engine publish for %s failed: %s", record_id, exc)
            return 0


class NoopPublisher(Publisher):
    """Logs publishes instead of writing (used when auto-publish is off)."""

    def publish(self, record_id: str, payload: dict, source_text: str = "") -> int:
        if record_id:
            log.info("Would publish enrichment for record %s (auto_publish off)", record_id)
        return 0
