#!/usr/bin/env python3
"""V3 Pipeline Orchestrator — runs the complete Compass Evidence Pipeline V3.

Usage:
  python3 scripts/28_v3_run.py [--step registry|fetch|extract|map|dedup|validate|all]
                               [--sources 5]  # limit sources for pilot
                               [--skip-fetch]  # skip fetch, use existing
"""

import sys, os, json, argparse, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def step_summary(name, elapsed, ok=True):
    status = "OK" if ok else "FAILED"
    print(f"\n  [{status}] {name} ({elapsed:.1f}s)")


def run(argv=None):
    parser = argparse.ArgumentParser(description="Compass Evidence Pipeline V3")
    parser.add_argument("--step", default="all",
                        choices=["registry", "fetch", "extract", "map", "dedup", "validate", "all"],
                        help="Pipeline step to run")
    parser.add_argument("--sources", type=int, default=None,
                        help="Limit number of sources (for pilot runs)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip fetch step, use existing fetched data")
    parser.add_argument("--extract-path", type=str, default=None,
                        help="Path to extraction_v3.jsonl (for map step)")
    args = parser.parse_args(argv)

    # Print pipeline info
    print_header("COMPASS EVIDENCE PIPELINE V3")
    print(f"  Step:        {args.step}")
    print(f"  Sources:     {args.sources or 'all enabled'}")
    print(f"  Skip fetch:  {args.skip_fetch}")
    print(f"  Base:        {BASE}")

    start = time.time()

    # ── Step 1: Source Registry ──
    if args.step in ("registry", "all"):
        print_header("STEP 1: Source Registry")
        t0 = time.time()
        registry_script = BASE / "scripts" / "21_v3_source_registry.py"
        rc = os.system(f"python3 {registry_script}")
        step_summary("Source Registry", time.time() - t0, ok=rc == 0)
        if rc != 0:
            print("ERROR: Source registry failed. Aborting.")
            sys.exit(1)

    # ── Step 2: Fetch ──
    if args.step in ("fetch", "all") and not args.skip_fetch:
        print_header("STEP 2: Fetch Case Studies")
        t0 = time.time()
        fetch_script = BASE / "scripts" / "24_v3_fetch.py"
        if args.sources:
            rc = os.system(f"python3 {fetch_script} --sources {args.sources}")
        else:
            rc = os.system(f"python3 {fetch_script}")
        step_summary("Fetch", time.time() - t0, ok=rc == 0)

    # ── Step 3: Extract ──
    if args.step in ("extract", "all"):
        print_header("STEP 3: LLM Extraction")
        t0 = time.time()
        extract_script = BASE / "scripts" / "23_v3_extract.py"
        rc = os.system(f"python3 {extract_script}")
        step_summary("Extraction", time.time() - t0, ok=rc == 0)
        if rc != 0:
            print("ERROR: Extraction failed. Check DEEPSEEK_API_KEY.")
            sys.exit(1)

    # ── Step 4: Map to DB ──
    if args.step in ("map", "all"):
        print_header("STEP 4: Map to Database")
        t0 = time.time()
        map_script = BASE / "scripts" / "25_v3_map_to_db.py"
        env = os.environ.copy()
        rc = os.system(f"python3 {map_script}")
        step_summary("Map to DB", time.time() - t0, ok=rc == 0)

    # ── Step 5: Dedup ──
    if args.step in ("dedup", "all"):
        print_header("STEP 5: Deduplication")
        t0 = time.time()
        dedup_script = BASE / "scripts" / "26_v3_dedup.py"
        rc = os.system(f"python3 {dedup_script}")
        step_summary("Dedup", time.time() - t0, ok=rc == 0)

    # ── Step 6: Validate ──
    if args.step in ("validate", "all"):
        print_header("STEP 6: Validation")
        t0 = time.time()
        validate_script = BASE / "scripts" / "27_v3_validate.py"
        rc = os.system(f"python3 {validate_script}")
        step_summary("Validation", time.time() - t0, ok=rc == 0)

    # ── Summary ──
    total_elapsed = time.time() - start
    print_header("PIPELINE COMPLETE")
    print(f"  Total time: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print(f"  Output DB:  data/collector_v3.db")
    print(f"  Registry:   data/source_registry.json")
    print(f"  Extractions: data/extraction/extraction_v3.jsonl")

    # Print a quick report
    v3_db = BASE / "data" / "collector_v3.db"
    if v3_db.exists():
        print(f"\n  To validate: python3 scripts/27_v3_validate.py")

    print()


if __name__ == "__main__":
    run()
