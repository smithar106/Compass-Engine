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


from compass_collector.analysis.evidence_flow import classify_evidence_flow as classify  # noqa: E402


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
