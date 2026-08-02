"""Auto-publish: write validated enrichment back to the collector database.

Only writes when auto-publish is enabled and a collector DB path is known.
Otherwise it logs what *would* have been written.
"""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger("compass_agent.publish")


class Publisher:
    """Writes validated enrichment back to a collector SQLite database."""

    def __init__(self, db_path: str = "", enabled: bool = False) -> None:
        self.db_path = db_path
        self.enabled = enabled

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.db_path)

    def publish(self, record_id: str, payload: dict) -> int:
        """Update one intervention record. Returns number of rows updated."""
        if not self.active or not record_id:
            return 0
        try:
            conn = sqlite3.connect(self.db_path)
        except sqlite3.Error as exc:
            log.warning("Cannot open collector DB for publish: %s", exc)
            return 0
        try:
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


class NoopPublisher(Publisher):
    """Logs publishes instead of writing (used when auto-publish is off)."""

    def publish(self, record_id: str, payload: dict) -> int:
        if record_id:
            log.info("Would publish enrichment for record %s (auto_publish off)", record_id)
        return 0
