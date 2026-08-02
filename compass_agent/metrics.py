"""Enrichment metrics report.

Item 4 of the follow-up: cost efficiency, rejection rate, and richness of the
agent's enrichment work. Reads the agent's persistent store (AGENT_STORE_DB)
and, when a collector DB is available (AGENT_CANDIDATE_DB), the richness of the
records it published.

Provenance accuracy and overwrite conflicts are not measurable from the current
store (it records results, not pre-image values); they are reported as "not
measured" with the data needed to close the gap.
"""

from __future__ import annotations

import sqlite3
import json
import os
from typing import Optional


def _connect(path: str):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def compute_metrics(store_db: str = "", collector_db: str = "") -> dict:
    """Compute enrichment metrics from the agent store + optional collector DB."""
    report: dict = {
        "attempted_records": 0,
        "valid_enrichments": 0,
        "invalid_enrichments": 0,
        "skipped": 0,
        "rejection_rate": 0.0,
        "total_cost_usd": 0.0,
        "cost_per_attempted_record": None,
        "cost_per_valid_enrichment": None,
        "cost_per_usable_record": None,
        "cost_per_rich_record": None,
        "usable_records": 0,
        "rich_records": 0,
        "provenance_accuracy": None,
        "overwrite_conflicts": None,
        "notes": [],
    }

    # ── Agent store: enrichment_results ──────────────────────────────────
    if store_db and os.path.exists(store_db):
        try:
            conn = _connect(store_db)
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost),0), COALESCE(SUM(valid),0) FROM enrichment_results"
            ).fetchone()
            conn.close()
            attempts, total_cost, valid = int(row[0]), float(row[1]), int(row[2])
            report["attempted_records"] = attempts
            report["valid_enrichments"] = valid
            report["invalid_enrichments"] = attempts - valid
            report["total_cost_usd"] = round(total_cost, 6)
            report["rejection_rate"] = round((attempts - valid) / attempts, 3) if attempts else 0.0
            report["cost_per_attempted_record"] = round(total_cost / attempts, 6) if attempts else None
            report["cost_per_valid_enrichment"] = round(total_cost / valid, 6) if valid else None

            # skipped records come from claims marked 'skipped'
            try:
                conn = _connect(store_db)
                skipped = conn.execute(
                    "SELECT COUNT(*) FROM claims WHERE status='skipped'"
                ).fetchone()[0]
                conn.close()
                report["skipped"] = int(skipped)
            except sqlite3.Error:
                pass
        except (sqlite3.Error, OSError) as exc:
            report["notes"].append(f"store read failed: {exc}")
    else:
        report["notes"].append("no agent store (AGENT_STORE_DB unset or missing)")

    # ── Collector DB: richness of published records ──────────────────────
    if collector_db and os.path.exists(collector_db):
        try:
            conn = _connect(collector_db)
            rows = conn.execute(
                "SELECT implementation_richness, COUNT(*) FROM intervention_records"
                " WHERE review_status='agent_enriched' GROUP BY implementation_richness"
            ).fetchall()
            conn.close()
            usable = rich = 0
            for richness, n in rows:
                if richness in ("rich", "usable"):
                    usable += int(n)
                if richness == "rich":
                    rich += int(n)
            report["usable_records"] = usable
            report["rich_records"] = rich
            if report["total_cost_usd"]:
                report["cost_per_usable_record"] = round(report["total_cost_usd"] / usable, 6) if usable else None
                report["cost_per_rich_record"] = round(report["total_cost_usd"] / rich, 6) if rich else None
        except (sqlite3.Error, OSError) as exc:
            report["notes"].append(f"collector read failed: {exc}")
    else:
        report["notes"].append("no collector DB (AGENT_CANDIDATE_DB unset or missing)")

    report["notes"].append(
        "provenance_accuracy/overwrite_conflicts require a gold set / pre-image "
        "tracking and are not measured by the current store."
    )
    return report


def print_metrics(report: dict) -> None:
    print("Compass Evidence Agent — enrichment metrics")
    print(f"  attempted records:        {report['attempted_records']}")
    print(f"  valid enrichments:        {report['valid_enrichments']}")
    print(f"  invalid enrichments:      {report['invalid_enrichments']}")
    print(f"  skipped:                  {report['skipped']}")
    print(f"  rejection rate:           {report['rejection_rate']:.1%}")
    print(f"  total cost:               ${report['total_cost_usd']:.6f}")
    print(f"  cost per attempted:       ${report['cost_per_attempted_record'] if report['cost_per_attempted_record'] is not None else '-'}")
    print(f"  cost per valid:           ${report['cost_per_valid_enrichment'] if report['cost_per_valid_enrichment'] is not None else '-'}")
    print(f"  cost per usable record:   ${report['cost_per_usable_record'] if report['cost_per_usable_record'] is not None else '-'}")
    print(f"  cost per rich record:     ${report['cost_per_rich_record'] if report['cost_per_rich_record'] is not None else '-'}")
    print(f"  provenance accuracy:      {report['provenance_accuracy'] if report['provenance_accuracy'] is not None else 'not measured'}")
    print(f"  overwrite conflicts:      {report['overwrite_conflicts'] if report['overwrite_conflicts'] is not None else 'not measured'}")
    for note in report["notes"]:
        print(f"  note: {note}")
