#!/usr/bin/env python3
"""Golden relevance evaluation for the 10-problem retrieval benchmark.

Deterministic, predicate-based relevance labeling so Precision@5 / Precision@10
are stable across retrieval score changes:

  A record is RELEVANT for a problem if its canonical workflow tag
  (workflow_normalized.value) reconciles to the problem's canonical workflow
  via the relations taxonomy (EXACT/ALIAS/RELATED), OR its free text contains
  the problem's keyword set.

This replaces hand-picked per-record labels, which drifted when the scoring
changes reshuffled the top-N. Predicates are reproducible and inspectable.

Usage:
    python scripts/golden_relevance.py /tmp/retrieval_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.analysis.workflow_relations import (
    canonical_workflows_for,
    resolve_query_workflow,
)

# Per-problem: canonical workflow + free-text keyword set for the "somewhat"
# (weak) relevance tier.
PROBLEM_WORKFLOWS: dict[str, str] = {
    "slow-customer-onboarding": "onboarding",
    "manual-invoice-processing": "invoice_processing",
    "misrouted-support": "ticketing",
    "trapped-knowledge": "knowledge_base",
    "sales-handoff-rework": "order_processing",
    "repetitive-reporting": "analytics_reporting",
    "late-escalations": "relationship_management",
    "manual-forecasting": "forecasting",
    "hard-to-find-information": "self_service",
    "slow-employee-ramp": "onboarding",
}

PROBLEM_KEYWORDS: dict[str, list[str]] = {
    "slow-customer-onboarding": ["onboard", "customer onboarding"],
    "manual-invoice-processing": ["invoice", "accounts payable", "payable"],
    "misrouted-support": ["ticket", "support", "routing", "triage", "contact center"],
    "trapped-knowledge": ["knowledge", "document", "search"],
    "sales-handoff-rework": ["handoff", "quote", "order to cash", "sales order", "cpq"],
    "repetitive-reporting": ["report", "analytics", "dashboard", "bi "],
    "late-escalations": ["escalat", "churn", "retention", "at-risk", "customer health"],
    "manual-forecasting": ["forecast", "demand planning"],
    "hard-to-find-information": ["search", "information", "knowledge", "self service"],
    "slow-employee-ramp": ["onboard", "new hire", "training", "ramp"],
}


def classify(report: dict) -> dict:
    results = {}
    for problem in report["problems"]:
        pid = problem["problem"]
        q_wf = resolve_query_workflow(PROBLEM_WORKFLOWS.get(pid, ""))
        keywords = PROBLEM_KEYWORDS.get(pid, [])
        top = problem["top_20"]
        p5 = p10 = 0
        labels = []
        for i, t in enumerate(top[:10], 1):
            record_canonical = t.get("record_canonical") or ""
            intervention = t.get("intervention") or ""
            org = t.get("organization") or ""
            text = f"{org} {intervention}".lower()
            # Relevance via canonical workflow reconciliation.
            wf_relevant = False
            if record_canonical and q_wf:
                wf_relevant = q_wf in canonical_workflows_for(record_canonical)
            # Relevance via keyword presence in text.
            kw_hit = any(k in text for k in keywords)
            label = "RELEVANT" if wf_relevant else ("WEAK" if kw_hit else "IRRELEVANT")
            labels.append(label)
            if label == "RELEVANT":
                if i <= 5:
                    p5 += 1
                p10 += 1
        results[pid] = {
            "precision@5": p5 / 5,
            "precision@10": p10 / min(10, len(top)),
            "relevant": labels.count("RELEVANT"),
            "weak": labels.count("WEAK"),
            "irrelevant": labels.count("IRRELEVANT"),
        }
    return results


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/golden_relevance.py /tmp/retrieval_report.json")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        report = json.load(f)
    results = classify(report)
    print(f"\n=== GOLDEN RELEVANCE (predicate-based, from {sys.argv[1]}) ===\n")
    print(f"{'problem':<28} {'P@5':>5} {'P@10':>6} {'rel':>4} {'weak':>5} {'irrel':>6}")
    print("-" * 62)
    for pid, r in results.items():
        print(
            f"{pid:<28} {r['precision@5']:>5.2f} {r['precision@10']:>6.2f} "
            f"{r['relevant']:>4} {r['weak']:>5} {r['irrelevant']:>6}"
        )
    avg5 = sum(r["precision@5"] for r in results.values()) / len(results)
    avg10 = sum(r["precision@10"] for r in results.values()) / len(results)
    print("-" * 62)
    print(f"{'AVERAGE':<28} {avg5:>5.2f} {avg10:>6.2f}")


if __name__ == "__main__":
    main()
