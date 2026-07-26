#!/usr/bin/env python3
"""V3: Validation and retrieval tests for collector_v3.db.

Runs retrieval tests for key workflows and reports evidence quality metrics.
"""

import sys, json, os
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

V3_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "collector_v3.db"
os.environ["COLLECTOR_DATABASE_URL"] = f"sqlite:///{V3_DB_PATH}"

from compass_collector.database import init_db, get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag

TEST_WORKFLOWS = [
    "customer support",
    "invoice processing",
    "sales qualification",
    "claims processing",
    "knowledge management",
    "HR onboarding",
    "procurement",
    "field service",
    "maintenance",
    "inventory planning",
    "forecasting",
    "fraud detection",
    "contract review",
    "routing",
    "dispatch",
    "accounts payable",
    "employee onboarding",
    "IT service desk",
    "supply chain",
    "order management",
]


def workflow_match(rec, workflow: str) -> bool:
    wf = workflow.lower()
    title = (rec.intervention_title or "").lower()
    desc = (rec.intervention_description or "").lower()
    problem = (rec.problem_statement or "").lower()
    extra = rec.intervention_components or {}
    if isinstance(extra, dict):
        extra_wf = (extra.get("workflow") or "").lower()
    else:
        extra_wf = ""
    return any(wf in t for t in [title, desc, problem, extra_wf])


def main():
    init_db()
    session = get_session()

    records = session.query(InterventionRecord).all()
    print(f"Total records: {len(records)}")

    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0}
    for rec in records:
        extra = rec.intervention_components or {}
        if isinstance(extra, dict):
            tier = extra.get("evidence_tier", "unknown")
        else:
            tier = "unknown"
        if tier in tier_counts:
            tier_counts[tier] += 1

    print(f"\nEvidence tiers:")
    for t, c in tier_counts.items():
        print(f"  {t}: {c}")
    gold_score = tier_counts.get("tier1", 0) * 10 + tier_counts.get("tier2", 0) * 5 + tier_counts.get("tier3", 0) * 1
    print(f"  Evidence quality score: {gold_score}")

    # Gold/Silver/Bronze counts (for API consumption)
    metrics = session.query(MetricRecord).count()
    flags = session.query(QualityFlag).count()
    vendors = len([r for r in records if r.vendor_reported])
    with_outcomes = len([r for r in records if r.has_post_measurement])
    with_baseline = len([r for r in records if r.has_baseline])
    print(f"\nMetrics: {metrics}")
    print(f"Quality flags: {flags}")
    print(f"Vendor reported: {vendors}")
    print(f"With outcomes: {with_outcomes}")
    print(f"With baseline: {with_baseline}")

    # Retrieval tests
    print(f"\n{'='*60}")
    print(f"RETRIEVAL TESTS")
    print(f"{'='*60}")

    for workflow in TEST_WORKFLOWS:
        matching = [r for r in records if workflow_match(r, workflow)]
        t1 = len([r for r in matching if (r.intervention_components or {}).get("evidence_tier") == "tier1"])
        t2 = len([r for r in matching if (r.intervention_components or {}).get("evidence_tier") == "tier2"])
        t3 = len([r for r in matching if (r.intervention_components or {}).get("evidence_tier") == "tier3"])

        if t1 + t2 + t3 > 0:
            print(f"\n  {workflow}:")
            print(f"    Tier 1: {t1}  Tier 2: {t2}  Tier 3: {t3}")
            if t1 > 0:
                best = [r for r in matching if (r.intervention_components or {}).get("evidence_tier") == "tier1"][:3]
                for b in best:
                    print(f"    - {b.organization_name}: {b.intervention_title[:80]}")
        else:
            print(f"\n  {workflow}: NO MATCHES")

    # Sources report
    print(f"\n{'='*60}")
    print(f"SOURCES REPORT")
    print(f"{'='*60}")
    sources = defaultdict(lambda: {"tier1": 0, "tier2": 0, "tier3": 0})
    for rec in records:
        extra = rec.intervention_components or {}
        tier = extra.get("evidence_tier", "unknown") if isinstance(extra, dict) else "unknown"
        src = rec.source_id or "unknown"
        if tier in sources[src]:
            sources[src][tier] += 1

    for src, counts in sorted(sources.items(), key=lambda x: -sum(x[1].values())):
        if sum(counts.values()) > 0:
            print(f"  {src[:50]}: T1={counts['tier1']} T2={counts['tier2']} T3={counts['tier3']}")

    # Missing evidence
    print(f"\n{'='*60}")
    print(f"QUALITY GAPS")
    print(f"{'='*60}")
    missing_org = len([r for r in records if not r.organization_name])
    missing_outcome = len([r for r in records if not r.has_post_measurement])
    missing_baseline = len([r for r in records if not r.has_baseline])
    print(f"  Missing organization: {missing_org}")
    print(f"  Missing outcomes: {missing_outcome}")
    print(f"  Missing baseline: {missing_baseline}")

    session.close()

    print(f"\n{'='*60}")
    print(f"VALIDATION COMPLETE")


if __name__ == "__main__":
    main()
