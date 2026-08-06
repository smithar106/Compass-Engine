#!/usr/bin/env python3
"""Org Attribute Recovery Worker — LLM refinery for geography + company size.

Recovers geography and employee count from source document bodies for records
the deterministic backfill could not classify (regex ceiling: geography 3.4%,
employee count 0.8%). Writes into organization_normalized with provenance.

Usage:
  ./venv/bin/python scripts/org_attribute_recovery.py --db collector_v3.db --dry-run
  ./venv/bin/python scripts/org_attribute_recovery.py --db collector_v3.db --limit 5000 --max 200
  # API key: DEEPSEEK_API_KEY (default provider: deepseek)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="path to collector_v3.db")
    parser.add_argument("--limit", type=int, default=500, help="records to scan")
    parser.add_argument("--max", dest="max_applications", type=int, default=5, help="records to process this pass")
    parser.add_argument("--concurrency", type=int, default=1, help="LLM concurrency")
    parser.add_argument("--api-key", default="", help="LLM API key (default: env)")
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "deepseek"), help="deepseek|anthropic")
    parser.add_argument("--dry-run", action="store_true", help="print candidates, call nothing")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get(
        "ANTHROPIC_API_KEY" if args.provider == "anthropic" else "DEEPSEEK_API_KEY", ""
    )

    from compass_agent.org_attribute_recovery import run_org_attribute_recovery

    report = run_org_attribute_recovery(
        args.db,
        api_key=api_key,
        provider=args.provider,
        max_applications=args.max_applications,
        concurrency=args.concurrency,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print("Org Attribute Recovery Worker report")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
