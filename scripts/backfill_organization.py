#!/usr/bin/env python3
"""Backfill: normalize existing evidence records onto the canonical taxonomy.

Phase 3 of the organization/industry upgrade. Normalizes every intervention
record's organization name, industry, employee count, geography, and
operational function, writing normalized values with full provenance into
``intervention_records.organization_normalized`` (raw values are preserved).

Usage:
  ./venv/bin/python scripts/backfill_organization.py --dry-run
  ./venv/bin/python scripts/backfill_organization.py            # writes to DB
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.models.intervention import InterventionRecord  # noqa: E402,F401
from compass_collector.database import init_db, get_session  # noqa: E402
from compass_collector.organization.backfill import run_backfill  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--limit", type=int, default=None, help="limit record count")
    parser.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        report = run_backfill(session, dry_run=args.dry_run, limit=args.limit)
    finally:
        session.close()

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print("Organization backfill report")
        print(f"  dry_run: {report['dry_run']}   records: {report['total_records']}   written: {report['written']}")
        for field, cov in report["field_coverage"].items():
            print(f"  {field:22s} {cov['present']:5d}/{cov['total']} ({cov['pct']}%)")
        print(f"  unmapped industry values: {report['unmapped_industry_count']}")
        for raw, count in report["unmapped_industries_top"][:15]:
            print(f"    {count}x  {raw}")


if __name__ == "__main__":
    main()
