#!/usr/bin/env python3
"""Classify every evidence record by whether it has a clear pre -> intervention
-> post flow with attribution, and mark the rest as archived.

A record is `flow_complete` (usable by the recommendation engine) only when ALL
of the following hold:

  PRE          a documented baseline — has_baseline, problem_baseline_description,
               or a metric with a baseline_value.
  INTERVENTION a specific intervention — intervention_families AND intervention_title.
  POST         a documented outcome — a metric with post_value / percentage_change /
               absolute_change.
  SOURCE       a resolvable source document — document_id present.
  ATTRIBUTION  outcome_provenance recorded (how the outcome is substantiated).

Everything else is `archived`: retained in the database but excluded from
recommendation retrieval (fail-closed default).

Usage:
  COLLECTOR_DATABASE_URL=sqlite:///data/collector_v3.db \
    python scripts/classify_evidence_flow.py [--apply] [--report out.json]

Without --apply it only reports (dry run).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session, init_db
from compass_collector.models.intervention import InterventionRecord, MetricRecord


def classify(session) -> dict:
    metrics: dict = {}
    for m in session.query(MetricRecord).all():
        metrics.setdefault(m.intervention_id, []).append(m)

    records = session.query(InterventionRecord).all()

    def has_pre(r, ms) -> bool:
        return (
            bool(r.has_baseline)
            or bool(r.problem_baseline_description)
            or any(m.baseline_value is not None for m in ms)
        )

    def has_post(ms) -> bool:
        return any(
            m.post_value is not None
            or m.percentage_change is not None
            or m.absolute_change is not None
            for m in ms
        )

    def has_intervention(r) -> bool:
        return bool(r.intervention_families) and bool(r.intervention_title)

    def has_source(r) -> bool:
        return bool(r.document_id)

    def has_attribution(r) -> bool:
        return bool(r.outcome_provenance)

    flow_ids: list[str] = []
    tiers = Counter()
    keep_by_provenance = Counter()
    keep_by_source_type = Counter()

    for r in records:
        ms = metrics.get(r["id"] if isinstance(r, dict) else r.id, [])
        pre, post = has_pre(r, ms), has_post(ms)
        interv, src, attr = has_intervention(r), has_source(r), has_attribution(r)
        core = pre and post and interv
        if core:
            tiers["pre+intervention+post"] += 1
        if core and src:
            tiers["+source"] += 1
        if core and src and attr:
            tiers["+attribution (flow_complete)"] += 1
            flow_ids.append(r.id)
            keep_by_provenance[r.outcome_provenance or "none"] += 1
            keep_by_source_type[r.source_type or "none"] += 1

    return {
        "total": len(records),
        "tiers": dict(tiers),
        "flow_complete": len(flow_ids),
        "archived": len(records) - len(flow_ids),
        "keep_by_provenance": dict(keep_by_provenance),
        "keep_by_source_type": dict(keep_by_source_type),
        "flow_ids": flow_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write evidence_status")
    parser.add_argument("--report", default="/tmp/evidence_flow_report.json")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        result = classify(session)
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "total": result["total"],
            "tiers": result["tiers"],
            "flow_complete": result["flow_complete"],
            "archived": result["archived"],
            "keep_by_provenance": result["keep_by_provenance"],
            "keep_by_source_type": result["keep_by_source_type"],
        }
        Path(args.report).write_text(json.dumps(report, indent=2))

        print(f"\n=== EVIDENCE FLOW CLASSIFICATION ({'APPLY' if args.apply else 'DRY RUN'}) ===\n")
        print(f"  total records:        {result['total']}")
        for k, v in result["tiers"].items():
            print(f"  {k:<28} {v}")
        print(f"  {'FLOW_COMPLETE (keep)':<28} {result['flow_complete']}")
        print(f"  {'ARCHIVED':<28} {result['archived']}")
        print(f"\n  keep by outcome_provenance: {result['keep_by_provenance']}")
        print(f"  keep by source_type:        {result['keep_by_source_type']}")
        print(f"\n  report: {args.report}")

        if args.apply:
            flow = set(result["flow_ids"])
            updated = 0
            for r in session.query(InterventionRecord).all():
                want = "flow_complete" if r.id in flow else "archived"
                if r.evidence_status != want:
                    r.evidence_status = want
                    updated += 1
            session.commit()
            print(f"\n  APPLIED: {updated} records updated.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
