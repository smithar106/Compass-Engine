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


# Keys stripped from the public (product-facing) gap report. The full report
# includes agent-internal hunt directives (composed search terms, which source
# library to crawl next, vendor diversity targets); the product UI sees the
# decision-coverage KPI, dimension coverage, and the ranked shopping list
# WITHOUT those operational directives.
_PUBLIC_STRIP_KEYS = ("search_terms", "source_library_priority", "vendor_diversity_target", "data_limited_fields")


def _public_report(data: dict) -> dict:
    """UI-shaped projection of a Gap Engine v2 report.

    Keeps everything the product UI renders (decision coverage per function,
    dimension coverage, per-need scores + targets) but strips the agent-internal
    hunt directives from every need.
    """
    for bucket in ("needs", "shopping_list"):
        for need in data.get(bucket) or []:
            if not isinstance(need, dict):
                continue
            for key in _PUBLIC_STRIP_KEYS:
                need.pop(key, None)
            sl = need.get("shopping_list")
            if isinstance(sl, dict):
                for key in _PUBLIC_STRIP_KEYS:
                    sl.pop(key, None)
    return data


@router.get("/gaps")
def evidence_gaps(request: Request = None, top: int = 20, min_impact: float = 0.0):
    """Evidence Gap Engine v2 report — decision coverage KPI + shopping list.

    Dual-mode: with a valid agent key (``X-Compass-Agent-Key``) the full report
    is returned including hunt directives (composed search terms, source-library
    priority, vendor diversity targets). Public reads get the UI-shaped report
    — decision coverage by function, dimension coverage, and the ranked
    shopping list without the agent-internal directives — so the product UI can
    surface "where evidence is deep and where we are actively filling".
    """
    agent = bool(request) and _authorized(request)

    from compass_agent.evidence_gap import run_gap_engine

    db = get_session()
    try:
        report = run_gap_engine(session=db, top_n=top, min_impact=min_impact)
    finally:
        db.close()
    data = report.to_dict()
    if not agent:
        data = _public_report(data)
    return data
