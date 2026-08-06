#!/usr/bin/env python3
"""Workflow Recovery Worker — LLM refinery for records with unknown workflows.

Recovers the primary operational workflow from the source document body for
records deterministic keyword inference could not classify, then maps the
recovered phrase onto the canonical ALL_WORKFLOWS taxonomy.

Usage:
  ./venv/bin/python scripts/workflow_recovery.py --db /data/collector_v3.db --dry-run
  ./venv/bin/python scripts/workflow_recovery.py --db /data/collector_v3.db --limit 100
  # API key: DEEPSEEK_API_KEY / ANTHROPIC_API_KEY (LLM_PROVIDER selects)
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
    parser.add_argument("--dry-run", action="store_true", help="print prompts, call nothing")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get(
        "ANTHROPIC_API_KEY" if args.provider == "anthropic" else "DEEPSEEK_API_KEY", ""
    )

    from compass_agent.workflow_recovery import run_workflow_recovery

    report = run_workflow_recovery(
        args.db,
        api_key=api_key,
        provider=args.provider,
        max_applications=args.max_applications,
        concurrency=args.concurrency,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print("Workflow Recovery Worker report")
    for k, v in report.items():
        if k == "top_workflows":
            print(f"  top recovered workflows:")
            for wf, n in v:
                print(f"      {n:4d}  {wf}")
        elif k == "taxonomy_candidates":
            print(f"  taxonomy candidates (unmapped LLM phrases):")
            for c in v:
                print(f"      {c}")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
