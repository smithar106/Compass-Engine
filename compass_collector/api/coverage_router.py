"""Decision Coverage — how well-supported each operational decision is.

The moat metric. Instead of counting records, this reports — for each business
function and workflow — how many high-quality (Gold/Silver) implementations
exist. Coverage levels are derived from both the count and the tier mix of
high-quality evidence, so the engine knows exactly where it is weak and can
target discovery there.

Keyed dimensions:
  * ``business_function`` — the operational area (e.g. finance, supply_chain).
  * ``workflow`` — a specific operational problem (e.g. invoice management).

Coverage levels:
  * excellent  — many high-quality implementations, meaningful tier breadth
  * good       — solid but thinner high-quality set
  * developing — few high-quality implementations (more Bronze below)
  * limited    — almost no high-quality implementations
  * absent     — no implementations at all
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from compass_collector.api.enrichment_router import _authorized
from compass_collector.api.evidence_tier import classify_evidence_tier
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord

router = APIRouter(prefix="/api/evidence", tags=["coverage"])

EXCELLENT_SOFT = 25
GOOD_SOFT = 10
DEV_MIN = 4
HIGH_QUALITY_TIERS = ("gold", "decision_grade")


def _coverage(total_high: int, ratio: float) -> str:
    """Derive a coverage label from raw counts and the high-quality ratio."""
    if total_high == 0:
        return "limited"
    if total_high >= EXCELLENT_SOFT and ratio >= 0.25:
        return "excellent"
    if total_high >= GOOD_SOFT or ratio >= 0.5:
        return "good"
    if total_high >= DEV_MIN or ratio >= 0.1:
        return "developing"
    return "limited"


def _workflow(rec: InterventionRecord) -> str:
    comps = rec.intervention_components or {}
    if isinstance(comps, dict):
        wf = comps.get("workflow") or ""
        if wf:
            return str(wf).strip()
    if rec.problem_business_function:
        return str(rec.problem_business_function[0]).strip()
    return "uncategorized"


@router.get("/coverage/decision")
def decision_coverage(request: Request = None):
    """Per business-function and per-workflow decision coverage."""
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

    funcs: dict[str, dict] = {}
    workflows: dict[str, dict] = {}

    for rec in records:
        tier = classify_evidence_tier(rec, metrics_by_id.get(rec.id, []), passages_by_id.get(rec.id, []))
        is_high = tier in HIGH_QUALITY_TIERS

        raw_funcs = [f for f in (rec.problem_business_function or []) if f] or ["uncategorized"]
        for fn in raw_funcs:
            b = funcs.setdefault(fn, {"total": 0, "gold": 0, "decision_grade": 0, "supporting": 0, "rejected": 0})
            b["total"] += 1
            b[tier] += 1

        wf = _workflow(rec)
        w = workflows.setdefault(wf, {"total": 0, "gold": 0, "decision_grade": 0, "supporting": 0, "rejected": 0})
        w["total"] += 1
        w[tier] += 1

    def _rows(buckets: dict) -> list:
        out = []
        for key, b in buckets.items():
            high = b["gold"] + b["decision_grade"]
            ratio = high / max(b["total"], 1)
            out.append({
                "key": key,
                "total": b["total"],
                "gold": b["gold"],
                "decision_grade": b["decision_grade"],
                "high_quality": high,
                "high_quality_pct": round(100 * ratio, 1),
                "coverage": _coverage(high, ratio),
            })
        return sorted(out, key=lambda x: -x["high_quality"])

    return {
        "dimension": "decision_coverage",
        "by_business_function": _rows(funcs),
        "by_workflow": _rows(workflows),
    }
