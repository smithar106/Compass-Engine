#!/usr/bin/env python3
"""Backfill: canonicalize vendors + technologies across the evidence graph.

Phase 4 of the canonical knowledge layer. Normalizes every intervention
record's vendors and software/products onto canonical keys (with families),
writing normalized values + full provenance into
``intervention_records.intervention_vendors_normalized`` and
``intervention_software_normalized`` (raw values are preserved).

Usage:
  ./venv/bin/python scripts/backfill_vendor_technology.py --dry-run
  ./venv/bin/python scripts/backfill_vendor_technology.py            # writes to DB
  ./venv/bin/python scripts/backfill_vendor_technology.py --json     # machine-readable
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.models.intervention import InterventionRecord  # noqa: E402,F401
from compass_collector.database import init_db, get_session  # noqa: E402
from compass_collector.organization.backfill import run_vendor_technology_backfill  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--limit", type=int, default=None, help="limit record count")
    parser.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        report = run_vendor_technology_backfill(session, dry_run=args.dry_run, limit=args.limit)
    finally:
        session.close()

    if args.as_json:
        print(json.dumps(report, indent=2))
        return

    print("Vendor/Technology canonicalization report")
    print(f"  dry_run: {report['dry_run']}   records: {report['total_records']}   written: {report['written']}")
    for dim in ("vendor", "technology"):
        d = report[dim]
        print(f"\n  {dim.upper():10s} raw_values={d['raw_values']}  mapped={d['mapped']} ({d['mapped_pct']}%)  "
              f"distinct_raw={d['distinct_raw']}  canonical={d['distinct_canonical']}")
        print("    top canonical:")
        for key, n in d["top_canonical"][:10]:
            print(f"      {n:5d}  {key}")
        if dim == "technology":
            print("    families:")
            for fam, n in d["families"][:10]:
                print(f"      {n:5d}  {fam}")
        print(f"    unmapped ({d['unmapped_count']}):")
        for raw, n in d["unmapped_top"][:10]:
            print(f"      {n}x  {raw}")


if __name__ == "__main__":
    main()
