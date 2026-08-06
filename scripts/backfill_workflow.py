#!/usr/bin/env python3
"""Backfill: canonicalize (and infer) workflows across the evidence graph.

Phase 4 completion of the canonical knowledge layer. Every intervention record
gets a canonical ``workflow_normalized`` payload: the stored free-text workflow
is normalized onto the ``ALL_WORKFLOWS`` taxonomy; records without a stored
workflow get one inferred from their title/problem statement. Raw values are
preserved.

Usage:
  ./venv/bin/python scripts/backfill_workflow.py --dry-run
  ./venv/bin/python scripts/backfill_workflow.py            # writes to DB
  ./venv/bin/python scripts/backfill_workflow.py --json     # machine-readable
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.models.intervention import InterventionRecord  # noqa: E402,F401
from compass_collector.database import init_db, get_session  # noqa: E402
from compass_collector.organization.backfill import run_workflow_backfill  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--limit", type=int, default=None, help="limit record count")
    parser.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        report = run_workflow_backfill(session, dry_run=args.dry_run, limit=args.limit)
    finally:
        session.close()

    if args.as_json:
        print(json.dumps(report, indent=2))
        return

    print("Workflow canonicalization report")
    print(f"  dry_run: {report['dry_run']}   records: {report['total_records']}   written: {report['written']}")
    print(f"  stored raw workflows : {report['stored_raw_workflows']}")
    print(f"  inferred from text   : {report['inferred_from_text']}")
    print(f"  mapped (>=0.5 conf)  : {report['mapped']} ({report['mapped_pct']}%)  canonical={report['canonical_distinct']}")
    print("  top canonical workflows:")
    for wf, n in report["top_workflows"][:15]:
        print(f"      {n:5d}  {wf}")
    print(f"  unmapped ({report['unmapped_count']}):")
    for wf, n in report["unmapped_top"][:10]:
        print(f"      {n}x  {wf}")


if __name__ == "__main__":
    main()
