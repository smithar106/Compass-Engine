#!/usr/bin/env python3
"""Retrieval benchmark for the 10 Compass prototype problems.

Reproducible before/after evaluation of workflow-taxonomy normalization on the
real collector database. For each of the 10 prototype problems it reports:

  * total matching candidates (records with a positive total similarity)
  * candidates above the retrieval threshold (total >= 0.25)
  * citable candidates (have intervention_families AND a quantified metric)
  * unique organizations
  * top 20 retrieved records with similarity breakdown, workflow match type,
    evidence quality, quantified-outcome availability, and intervention family

Run against the real DB:

  COLLECTOR_DATABASE_URL=sqlite:////tmp/compass_engine_probe/collector_v3.db \
    python scripts/retrieval_benchmark.py [--out /tmp/retrieval_report.json]

Use --legacy to run the old free-text-only workflow matcher (before).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.analysis.retrieval import (
    ImplementationQuery,
    compute_similarity,
    score_workflow_similarity,
    _get_components,
    _get_canonical_workflow,
)
from compass_collector.analysis.retrieval import SIMILARITY_WEIGHTS

RETRIEVAL_THRESHOLD = 0.35

# 10 prototype problems → structured query. The UX problem label is NOT the
# retrieval query; each resolves to a canonical workflow + problem concepts.
PROBLEMS: list[dict] = [
    {
        "id": "slow-customer-onboarding",
        "workflow": "onboarding",
        "business_function": "customer_success",
        "problem_terms": ["onboard", "customer onboarding", "time to value"],
        "desired_outcome": "time",
    },
    {
        "id": "manual-invoice-processing",
        "workflow": "invoice_processing",
        "business_function": "finance",
        "problem_terms": ["invoice", "accounts payable", "processing"],
        "desired_outcome": "cost",
    },
    {
        "id": "misrouted-support",
        "workflow": "ticketing",
        "business_function": "customer_support",
        "problem_terms": ["ticket", "routing", "triage", "support"],
        "desired_outcome": "time",
    },
    {
        "id": "trapped-knowledge",
        "workflow": "knowledge_base",
        "business_function": "operations",
        "problem_terms": ["knowledge", "document", "spreadsheet"],
        "desired_outcome": "quality",
    },
    {
        "id": "sales-handoff-rework",
        "workflow": "order_processing",
        "business_function": "sales",
        "problem_terms": ["handoff", "quote to order", "order to cash"],
        "desired_outcome": "quality",
    },
    {
        "id": "repetitive-reporting",
        "workflow": "analytics_reporting",
        "business_function": "operations",
        "problem_terms": ["report", "reporting", "dashboard"],
        "desired_outcome": "efficiency",
    },
    {
        "id": "late-escalations",
        "workflow": "relationship_management",
        "business_function": "customer_success",
        "problem_terms": ["escalation", "churn", "at risk", "customer health"],
        "desired_outcome": "quality",
    },
    {
        "id": "manual-forecasting",
        "workflow": "forecasting",
        "business_function": "finance",
        "problem_terms": ["forecast", "demand planning"],
        "desired_outcome": "efficiency",
    },
    {
        "id": "hard-to-find-information",
        "workflow": "self_service",
        "business_function": "operations",
        "problem_terms": ["search", "information", "retrieval"],
        "desired_outcome": "quality",
    },
    {
        "id": "slow-employee-ramp",
        "workflow": "onboarding",
        "business_function": "human_resources",
        "problem_terms": ["employee onboarding", "new hire", "ramp", "training"],
        "desired_outcome": "time",
    },
]


def _load_metrics(session) -> dict:
    metrics_by_id: dict = {}
    for m in session.query(MetricRecord).all():
        metrics_by_id.setdefault(m.intervention_id, []).append(m)
    return metrics_by_id


def _is_citable(rec: InterventionRecord, metrics: list[MetricRecord]) -> bool:
    if not rec.intervention_families:
        return False
    return any(
        m.percentage_change is not None or m.absolute_change is not None for m in metrics
    )


def _evidence_score(rec: InterventionRecord, metrics: list[MetricRecord]) -> float:
    score = 50.0
    if rec.independently_verified:
        score += 15
    if rec.sample_size and rec.sample_size > 1:
        score += 10
    quantified = sum(1 for m in metrics if m.percentage_change is not None or m.absolute_change is not None)
    score += min(15, quantified * 5)
    if rec.vendor_reported:
        score -= 10
    if rec.result_status in ("successful", "partial"):
        score += 10
    elif rec.result_status in ("failed", "abandoned"):
        score -= 10
    return max(0, min(100, score))


def _run_problem(problem: dict, metrics_by_id: dict, session, legacy: bool) -> dict:
    workflow = problem["workflow"]
    query = ImplementationQuery(
        workflow=workflow,
        business_function=problem["business_function"],
        desired_outcome=problem.get("desired_outcome", ""),
        max_results=50,
    )

    records = session.query(InterventionRecord).all()
    scored = []
    citable_total = 0
    for rec in records:
        metrics = metrics_by_id.get(rec.id, [])
        comps = _get_components(rec)
        record_workflow = comps.get("workflow") or ""
        record_canonical = _get_canonical_workflow(rec) if not legacy else ""
        if legacy:
            sim = compute_similarity_legacy(query, rec, metrics)
        else:
            sim = compute_similarity(query, rec, metrics)
        if sim["total"] <= 0:
            continue
        scored.append((sim, rec, metrics, record_workflow, record_canonical))
        if _is_citable(rec, metrics):
            citable_total += 1

    scored.sort(key=lambda x: -x[0]["total"])

    above_threshold = [s for s in scored if s[0]["total"] >= RETRIEVAL_THRESHOLD]
    above_citable = sum(1 for s in above_threshold if _is_citable(s[1], s[2]))

    orgs = set()
    for _sim, rec, _m, _rw, _rc in scored:
        if rec.organization_name:
            orgs.add(rec.organization_name)

    top = []
    for sim, rec, metrics, record_workflow, record_canonical in scored[:20]:
        wf_comp = sim["components"]["workflow"]
        top.append({
            "record_id": rec.id,
            "organization": rec.organization_name or "",
            "intervention": (rec.intervention_title or "")[:80],
            "total_similarity": sim["total"],
            "workflow_similarity": wf_comp.get("raw", 0),
            "workflow_match_type": wf_comp.get("match_type", "partial_text" if legacy else ""),
            "matched_workflows": wf_comp.get("matched_workflows", []),
            "record_canonical": wf_comp.get("record_canonical", record_canonical),
            "problem_similarity": sim["components"]["problem"].get("raw", 0),
            "evidence_score": _evidence_score(rec, metrics),
            "quantified_outcomes": sum(
                1 for m in metrics if m.percentage_change is not None or m.absolute_change is not None
            ),
            "intervention_families": (rec.intervention_families or [])[:3],
        })

    return {
        "problem": problem["id"],
        "workflow": workflow,
        "total_matching_candidates": len(scored),
        "above_threshold": len(above_threshold),
        "above_threshold_citable": above_citable,
        "citable_candidates": citable_total,
        "unique_organizations": len(orgs),
        "top_20": top,
    }


def compute_similarity_legacy(query, record, metrics):
    """Free-text-only workflow matching (the 'before' baseline)."""
    from compass_collector.analysis.retrieval import (
        score_problem_similarity,
        score_company_similarity,
        score_industry_similarity,
        score_intervention_similarity,
        score_outcome_similarity,
    )
    comps = _get_components(record)
    record_workflow = comps.get("workflow") or ""
    ps = score_problem_similarity(query.workflow, record) * SIMILARITY_WEIGHTS["problem_statement"]
    wf = score_workflow_similarity(query.workflow, record_workflow) * SIMILARITY_WEIGHTS["workflow"]
    cs = score_company_similarity(query, record) * SIMILARITY_WEIGHTS["company_size"]
    ind = score_industry_similarity(query, record) * SIMILARITY_WEIGHTS["industry"]
    inv = score_intervention_similarity(query, record) * SIMILARITY_WEIGHTS["intervention"]
    out = score_outcome_similarity(query, record, metrics) * SIMILARITY_WEIGHTS["outcome"]
    total = ps + wf + cs + ind + inv + out
    return {
        "total": round(total, 3),
        "components": {
            "workflow": {"raw": round(wf / SIMILARITY_WEIGHTS["workflow"], 2) if SIMILARITY_WEIGHTS["workflow"] else 0},
            "problem": {"raw": round(ps / SIMILARITY_WEIGHTS["problem_statement"], 2) if SIMILARITY_WEIGHTS["problem_statement"] else 0},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/retrieval_report.json")
    parser.add_argument("--legacy", action="store_true", help="run the before (free-text-only) matcher")
    parser.add_argument("--json", default=None, help="write machine-readable results here")
    args = parser.parse_args()

    session = get_session()
    metrics_by_id = _load_metrics(session)

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": "legacy" if args.legacy else "taxonomy",
        "problems": [_run_problem(p, metrics_by_id, session, args.legacy) for p in PROBLEMS],
    }

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n=== RETRIEVAL BENCHMARK ({'legacy' if args.legacy else 'taxonomy'}) ===\n")
    print(f"{'problem':<28} {'matched':>8} {'≥thr':>6} {'citable':>7} {'orgs':>5} {'citable≥thr':>10}")
    print("-" * 72)
    for p in report["problems"]:
        print(
            f"{p['problem']:<28} {p['total_matching_candidates']:>8} "
            f"{p['above_threshold']:>6} {p['citable_candidates']:>7} "
            f"{p['unique_organizations']:>5} {p['above_threshold_citable']:>10}"
        )

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2, default=str)

    print(f"\nFull report: {args.out}")


if __name__ == "__main__":
    main()
