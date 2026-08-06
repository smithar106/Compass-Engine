"""Recommendation Quality KPIs (Phase 3D).

Aggregates the decision-quality metrics that replace raw record counts:
  * Evidence quality — tier distribution and high-quality ratio of the library.
  * Coverage — share of distinct workflows/functions with meaningful
    high-quality implementation depth (mirrors Decision Coverage).
  * Implementation diversity — unique orgs, industries, vendors, workflows.
  * Evidence depth — quantified outcome metrics, baselines, timeframe.
  * Decision confidence — where recommendations + selections exist, the
    distribution of their confidence scores.

The point: every metric answers "will this make the next recommendation
better?", not "how many records do we have?".
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Request

from compass_collector.api.enrichment_router import _authorized
from compass_collector.api.evidence_tier import classify_evidence_tier
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord

router = APIRouter(prefix="/api/evidence", tags=["quality"])

HIGH_QUALITY_TIERS = ("gold", "silver")


def _coverage_goodish(coverage: str) -> bool:
    return coverage in ("excellent", "good")


@router.get("/quality")
def recommendation_quality(request: Request = None):
    """Library-level recommendation quality KPIs."""
    if not _authorized(request):
        return {"error": "unauthorized"}, 401

    db = get_session()
    try:
        records = db.query(InterventionRecord).all()
        metrics_by_id: dict = {}
        for m in db.query(MetricRecord).all():
            metrics_by_id.setdefault(m.intervention_id, []).append(m)
        passages_by_id: dict = {}
        for p in db.query(PassageRecord).all():
            passages_by_id.setdefault(p.intervention_id, []).append(p)
    finally:
        db.close()

    tiers = Counter()
    orgs: set = set()
    industries: set = set()
    vendors: set = set()
    workflows: set = set()
    funcs: set = set()
    measured_metrics = 0
    has_baseline = 0
    has_provenance = 0

    qual_by: dict[str, Counter] = {}

    for rec in records:
        tier = classify_evidence_tier(rec, metrics_by_id.get(rec.id, []), passages_by_id.get(rec.id, []))
        tiers[tier] += 1
        if rec.organization_name:
            orgs.add(rec.organization_name)
        for ind in rec.organization_industry or []:
            if ind:
                industries.add(str(ind).lower())
        for v in rec.intervention_vendors or []:
            if v:
                vendors.add(str(v))
        wf = _workflow(rec)
        if wf:
            workflows.add(wf)
        fn = rec.problem_business_function or ["uncategorized"]
        for f in fn:
            funcs.add(f)
            c = qual_by.setdefault(f, Counter())
            c[tier] += 1

        metrics = metrics_by_id.get(rec.id, [])
        q = sum(1 for m in metrics if m.percentage_change is not None or (m.absolute_change is not None and m.absolute_change != 0))
        measured_metrics += q
        if rec.has_baseline or rec.problem_baseline_description:
            has_baseline += 1
        if rec.implementation_provenance or rec.outcome_provenance:
            has_provenance += 1

    total = len(records)
    high = tiers["gold"] + tiers["silver"]

    # Coverage: share of functions whose high-quality depth is good/excellent.
    func_coverage = []
    for fn, c in qual_by.items():
        fh = c["gold"] + c["silver"]
        fratio = fh / max(sum(c.values()), 1)
        coverage = "absent" if fh == 0 else ("excellent" if fh >= 25 and fratio >= 0.25 else ("good" if fh >= 10 or fratio >= 0.5 else ("developing" if fh >= 4 or fratio >= 0.1 else "limited")))
        func_coverage.append({"function": fn, "high_quality": fh, "total": sum(c.values()), "coverage": coverage})
    func_covered = sum(1 for c in func_coverage if c["coverage"] in ("excellent", "good"))
    coverage_pct = round(100 * func_covered / max(len(func_coverage), 1), 1)

    return {
        "dimension": "recommendation_quality",
        "library_size": total,
        "evidence_quality": {
            "gold": tiers["gold"],
            "silver": tiers["silver"],
            "bronze": tiers["bronze"],
            "rejected": tiers["rejected"],
            "high_quality": high,
            "high_quality_pct": round(100 * high / max(total, 1), 1),
        },
        "coverage": {
            "functions": len(func_coverage),
            "functions_covered": func_covered,
            "coverage_pct": coverage_pct,
            "function_detail": sorted(func_coverage, key=lambda x: -x["high_quality"]),
        },
        "evidence_depth": {
            "measured_outcome_metrics": measured_metrics,
            "records_with_baseline": has_baseline,
            "records_with_provenance": has_provenance,
        },
        "implementation_diversity": {
            "unique_organizations": len(orgs),
            "unique_industries": len(industries),
            "unique_vendors": len(vendors),
            "unique_workflows": len(workflows),
        },
        "north_star": {
            "1_500_gold": tiers["gold"],  # progress toward the Gold north star
        },
    }


def _workflow(rec: InterventionRecord) -> str:
    comps = rec.intervention_components or {}
    if isinstance(comps, dict):
        wf = comps.get("workflow") or ""
        if wf:
            return str(wf).strip()
    if rec.problem_business_function:
        return str(rec.problem_business_function[0]).strip()
    return "uncategorized"