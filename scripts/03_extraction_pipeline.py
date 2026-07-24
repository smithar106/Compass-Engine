#!/usr/bin/env python3
"""
Compass Collector — LLM Extraction Pipeline

STAGE 1: Relevance Filtering (all documents, deterministic)
STAGE 2: Pilot Extraction (50 high-relevance docs, with DeepSeek API)
STAGE 3: Validation + Report
STAGE 4: (future) Full-scale extraction

Usage:
    python3 scripts/03_extraction_pipeline.py pilot      # 50-document pilot
    python3 scripts/03_extraction_pipeline.py full       # full relevant corpus (requires approval)
    python3 scripts/03_extraction_pipeline.py relevance  # relevance filter only
    python3 scripts/03_extraction_pipeline.py report     # show last report
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator


def run_pilot():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY environment variable not set")
        print("Set it with: export DEEPSEEK_API_KEY='sk-...'")
        sys.exit(1)

    orch = ExtractionOrchestrator()
    orch.set_api_key(api_key)

    # Load all documents and run relevance filter
    print("=" * 60)
    print("STAGE 1: Relevance Filtering (all documents)")
    print("=" * 60)
    result = orch.full_run(max_docs=500)

    print("\n" + result["report"])

    # Detailed cost estimate for full run
    if result["extractions"] > 0:
        cost_per_doc = result["cost"] / result["extractions"]
        high_count = result["relevance"].get("high_relevance", 0)
        possible_count = result["relevance"].get("possible_relevance", 0)
        total_relevant = high_count + possible_count
        estimated_full_cost = cost_per_doc * total_relevant
        print(f"\nEstimated full-run cost: ${estimated_full_cost:.4f}")
        print(f"  ({high_count} high + {possible_count} possible = {total_relevant} docs at ${cost_per_doc:.6f}/doc)")
        print(f"\nNext steps:")
        print(f"  1. Review: open ~/compass-collector/data/extraction/manual_review_sample.csv")
        print(f"  2. Approve full run with: python3 scripts/03_extraction_pipeline.py full")


def run_full():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY environment variable not set")
        sys.exit(1)

    orch = ExtractionOrchestrator()
    orch.set_api_key(api_key)
    print("=" * 60)
    print("STAGE 4: Full-Scale Extraction")
    print("=" * 60)
    result = orch.full_run()
    print("\n" + result["report"])


def run_relevance_only():
    orch = ExtractionOrchestrator()
    documents = orch.load_documents()
    print(f"Loaded {len(documents)} documents")
    results, counts = orch.run_relevance_filter(documents)
    print(f"High relevance: {counts['high_relevance']}")
    print(f"Possible relevance: {counts['possible_relevance']}")
    print(f"Not relevant: {counts['not_relevant']}")


def show_report():
    report_path = os.path.expanduser("~/compass-collector/data/extraction/extraction_run_report.md")
    if os.path.exists(report_path):
        print(open(report_path).read())
    else:
        print("No report found. Run a pipeline stage first.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "pilot":
        run_pilot()
    elif cmd == "full":
        run_full()
    elif cmd == "relevance":
        run_relevance_only()
    elif cmd == "report":
        show_report()
    else:
        print(f"Unknown: {cmd}")


if __name__ == "__main__":
    main()
