"""Retrieval evaluation harness.

Measures whether the ten-factor retrieval actually does what we think:

  - relevant-record recall @ K (top 10 / 25 / 50)
  - irrelevant-record rate in the top K
  - intervention-family ranking accuracy
  - field sensitivity (which profile fields most change the ranking)
  - weight sensitivity (is the system stable under small weight changes)

Runs against any record pool (the collector DB via evidence_ops.load_records, a
test pool, or live engine). Deterministic and reproducible.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from compass_agent.eval_set import EVAL_REQUESTS

log = logging.getLogger("compass_agent.eval")

WORKFLOW_KEYWORDS = {
    "invoice_processing": ["invoice", "payable", "payment", "reconcil", "billing"],
    "onboarding": ["onboard"],
    "ticketing": ["ticket", "support", "escalat", "help desk"],
    "lead_qualification": ["lead", "qualif", "prospect"],
    "marketing_automation": ["marketing", "campaign", "personaliz"],
    "ci_cd": ["ci cd", "ci/cd", "deploy", "build", "release"],
    "contract_review": ["contract", "clause", "agreement"],
    "supply_chain": ["supply", "inventory", "logistic", "fulfil"],
    "manufacturing": ["manufactur", "production", "assembly", "warehouse"],
    "customer_health": ["health", "churn", "retention", "at risk"],
    "financial_close": ["close", "reconcil", "reporting", "month end"],
    "claims_processing": ["claim", "underwrit"],
    "payroll": ["payroll", "pay"],
    "helpdesk": ["help desk", "helpdesk", "it service", "ticket"],
    "sales_forecasting": ["forecast", "demand", "sales"],
}


def _record_workflow(rec: Any) -> str:
    comps = getattr(rec, "intervention_components", None) or {}
    if isinstance(comps, dict):
        return str(comps.get("workflow") or "")
    return ""


def _record_canonical_industry(rec: Any) -> str:
    norm = getattr(rec, "organization_normalized", None) or {}
    if isinstance(norm, dict):
        return str((norm.get("primary_industry") or {}).get("value") or "")
    return ""


def _record_families(rec: Any) -> list[str]:
    fams = getattr(rec, "intervention_families", None) or []
    if not isinstance(fams, list):
        fams = [fams]
    canonical = []
    for f in fams:
        fam = str(f).lower()
        canonical.append(fam)
        try:
            from compass_collector.analysis.recommendation import get_family_for_subcategory

            mapped = get_family_for_subcategory(fam)
            if mapped:
                canonical.append(mapped.lower())
        except Exception:
            pass
    return list(dict.fromkeys(canonical))


def _record_result(rec: Any) -> str:
    return str(getattr(rec, "result_status", "") or "").lower()


def workflow_match(req_workflow: str, record_workflow: str) -> bool:
    if not req_workflow or not record_workflow:
        return False
    text = record_workflow.lower()
    for kw in WORKFLOW_KEYWORDS.get(req_workflow, [req_workflow.replace("_", " ")]):
        if kw in text:
            return True
    return False


def industry_match(req_industry: str, record_industry: str) -> bool:
    if not req_industry or not record_industry:
        return False
    from compass_collector.organization.taxonomy import normalize_industry

    req_canon = normalize_industry(req_industry)
    if req_canon.mapped:
        return record_industry == req_canon.canonical
    return req_industry.lower() in record_industry.lower()


def label_record(req: dict, rec: Any) -> str:
    """'relevant' | 'somewhat' | 'irrelevant'."""
    wf = workflow_match(req.get("workflow", ""), _record_workflow(rec))
    ind = industry_match(req.get("industry", ""), _record_canonical_industry(rec))
    if wf and ind:
        return "relevant"
    if wf or ind:
        return "somewhat"
    return "irrelevant"


def rank_records(profile: dict, records: list, weights: Optional[dict] = None) -> list[Any]:
    """Rank records by context fit for a profile (dedup by organization)."""
    from compass_collector.analysis.context_retrieval import (
        CONTEXT_FACTOR_WEIGHTS,
        ContextQuery,
        compute_context_similarity,
    )

    orig = CONTEXT_FACTOR_WEIGHTS.copy()
    if weights:
        CONTEXT_FACTOR_WEIGHTS.clear()
        CONTEXT_FACTOR_WEIGHTS.update(weights)

    q = ContextQuery(
        workflow=profile.get("workflow", ""),
        business_function=profile.get("business_function", ""),
        problem_statement=profile.get("problem_statement", ""),
        primary_industry=profile.get("industry", ""),
        industry_subsector=profile.get("subsector", ""),
        geography=profile.get("geography", ""),
    )
    try:
        emp = profile.get("company_size")
        if emp:
            q.employee_band = str(emp)
        scored = []
        for rec in records:
            fit = compute_context_similarity(q, rec, [])
            scored.append((fit.total, rec))
        scored.sort(key=lambda x: -x[0])
        seen = set()
        out = []
        for score, rec in scored:
            org = str(getattr(rec, "organization_name", "") or "").lower()
            if org and org in seen:
                continue
            seen.add(org)
            out.append(rec)
        return out
    finally:
        CONTEXT_FACTOR_WEIGHTS.clear()
        CONTEXT_FACTOR_WEIGHTS.update(orig)


def metrics_for_request(req: dict, ranked: list) -> dict:
    labels = [label_record(req, rec) for rec in ranked]
    total_relevant = sum(1 for l in labels if l == "relevant")
    total_somewhat = sum(1 for l in labels if l == "somewhat")
    out = {"id": req["id"], "total_relevant": total_relevant, "total_somewhat": total_somewhat}
    for k in (10, 25, 50):
        top = labels[:k]
        relevant = sum(1 for l in top if l == "relevant")
        somewhat = sum(1 for l in top if l == "somewhat")
        irrelevant = sum(1 for l in top if l == "irrelevant")
        out[f"recall@{k}"] = round(relevant / max(total_relevant, 1), 3)
        out[f"relevant_or_somewhat@{k}"] = round((relevant + somewhat) / max(total_relevant + total_somewhat, 1), 3)
        out[f"irrelevant@{k}"] = round(irrelevant / max(k, 1), 3)
    # family accuracy: top-10 ranked records' families overlap expected
    expected = set()
    for e in req.get("expected_families", []):
        expected.add(str(e).lower().replace(" ", "_"))
        try:
            from compass_collector.analysis.recommendation import get_family_for_subcategory

            mapped = get_family_for_subcategory(str(e))
            if mapped:
                expected.add(mapped.lower())
        except Exception:
            pass
    top_families = set()
    for rec in ranked[:10]:
        top_families.update(_record_families(rec))
    overlap = len(expected & top_families)
    out["family_accuracy"] = round(overlap / max(len(expected), 1), 3)
    return out


def run_retrieval_eval(records: list, requests: Optional[list] = None) -> dict:
    requests = requests if requests is not None else EVAL_REQUESTS
    per_request = []
    for req in requests:
        ranked = rank_records(req["profile"], records)
        per_request.append(metrics_for_request(req, ranked))
    # aggregate
    agg = {"requests": len(per_request)}
    for metric in ("recall@10", "recall@25", "recall@50", "relevant_or_somewhat@10",
                   "irrelevant@10", "family_accuracy"):
        vals = [r.get(metric, 0.0) for r in per_request]
        agg[metric] = round(sum(vals) / max(len(vals), 1), 3)
    return {"aggregate": agg, "per_request": per_request}


def _topk_set(ranked: list, k: int = 25) -> set:
    return {getattr(r, "id", None) for r in ranked[:k]}


def _rank_delta(base: list, perturbed: list, k: int = 25) -> float:
    """Normalized average rank displacement (0 = identical order, 1 = shuffled)."""
    base_ids = [getattr(r, "id", None) for r in base[:k]]
    pert_ids = [getattr(r, "id", None) for r in perturbed[:k]]
    pos_b = {rid: i for i, rid in enumerate(base_ids) if rid}
    pos_p = {rid: i for i, rid in enumerate(pert_ids) if rid}
    common = set(pos_b) & set(pos_p)
    if not common:
        return 1.0
    return round(sum(abs(pos_b[c] - pos_p[c]) for c in common) / max(len(common), 1) / k, 3)


def field_sensitivity(records: list, requests: Optional[list] = None) -> dict:
    """Perturb each profile field and measure how much the top-25 ranking
    changes (rank displacement) and whether the #1 recommendation flips."""
    requests = requests if requests is not None else EVAL_REQUESTS
    fields = {
        "industry": lambda p: {**p, "industry": ("retail_consumer" if p.get("industry", "technology") != "retail_consumer" else "technology")},
        "company_size": lambda p: {**p, "company_size": ("10000" if p.get("company_size", "1000") != "10000" else "10")},
        "business_function": lambda p: {**p, "business_function": "operations"},
        "desired_outcome": lambda p: {**p, "desired_outcome": "quality"},
    }
    out = {}
    for fname, perturb in fields.items():
        deltas = []
        flips = 0
        for req in requests:
            base = rank_records(req["profile"], records)
            perturbed = rank_records(perturb(req["profile"]), records)
            deltas.append(_rank_delta(base, perturbed))
            if _topk_set(base, 1) != _topk_set(perturbed, 1):
                flips += 1
        out[fname] = {
            "rank_delta": round(sum(deltas) / max(len(deltas), 1), 3),
            "top1_flip_rate": round(flips / max(len(requests), 1), 3),
        }
    return out


def weight_sensitivity(records: list, requests: Optional[list] = None) -> dict:
    """Perturb each retrieval weight ±0.05 (renormalized) and measure the
    average top-25 rank displacement vs baseline."""
    from compass_collector.analysis.context_retrieval import CONTEXT_FACTOR_WEIGHTS

    requests = requests if requests is not None else EVAL_REQUESTS
    baseline = CONTEXT_FACTOR_WEIGHTS.copy()
    out = {}
    for factor in list(baseline.keys()):
        for sign, label in ((1, "+0.05"), (-1, "-0.05")):
            w = dict(baseline)
            w[factor] = max(0.0, baseline[factor] + sign * 0.05)
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            deltas = []
            for req in requests:
                base = rank_records(req["profile"], records)
                perturbed = rank_records(req["profile"], records, weights=w)
                deltas.append(_rank_delta(base, perturbed))
            out[f"{factor}{label}"] = round(sum(deltas) / max(len(deltas), 1), 3)
    return out


def print_eval_report(eval_result: dict) -> None:
    agg = eval_result["aggregate"]
    print("Retrieval evaluation — aggregate")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    print("\nPer request:")
    for r in eval_result["per_request"]:
        print(f"  {r['id']:<34s} recall@10={r.get('recall@10')} @25={r.get('recall@25')} "
              f"irrel@10={r.get('irrelevant@10')} fam_acc={r.get('family_accuracy')}")
