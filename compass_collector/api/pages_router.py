"""Gold Record Pages — a first-class implementation asset.

Renders a single implementation as a structured, human-readable summary (an
"Implementation Intelligence" asset — the business-level view the user clicks
into). Not a row dump: it groups the stored model into narrated sections.

Sections:
  * organization — who, industry, size
  * problem       — the operational problem the implementation addressed
  * intervention  — what was implemented, category, vendors, technology
  * deployment    — how it was rolled out (strategy, teams, governance)
  * timeline      — measurement period, implementation time
  * outcomes      — quantified metrics with baselines and reported passages
  * lessons       — lessons learned, success factors, risks/challenges
  * evidence      — tier, richness, provenance, and a per-component breakdown
  * sources       — source_id / stored source_url
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from compass_collector.api.enrichment_router import _authorized
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord

router = APIRouter(prefix="/api/evidence", tags=["pages"])

GOLD_PAGE_COLUMNS = [
    "id", "organization_name", "organization_industry", "organization_geography",
    "organization_employee_band", "problem_statement", "problem_business_function",
    "intervention_title", "intervention_category", "intervention_components",
    "intervention_software", "intervention_vendors", "intervention_description",
    "intervention_measurement_period_value", "intervention_measurement_period_unit",
    "intervention_implementation_time_value", "intervention_implementation_time_unit",
    "result_status", "implementation_pattern", "implementation_partner",
    "rollout_strategy", "governance_model", "change_management", "training_approach",
    "adoption_approach", "pilot_structure", "lessons_learned", "success_factors",
    "failure_conditions", "implementation_challenges", "risks", "limitations",
    "unintended_consequences", "sample_size", "has_baseline", "independently_verified",
    "vendor_reported", "implementation_provenance", "outcome_provenance",
    "evidence_level", "implementation_richness", "source_id", "document_id",
    "review_status", "extracted_at",
]


def _is_gold(pages_tier: str) -> bool:
    return (pages_tier or "").lower() == "gold"


@router.get("/pages/{record_id}")
def gold_page(record_id: str, request: Request = None):
    """A structured implementation asset page."""
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")

    db = get_session()
    try:
        rec = db.query(InterventionRecord).filter_by(id=record_id).first()
        if not rec:
            raise HTTPException(status_code=404, detail="implementation not found")
        metrics = [m for m in db.query(MetricRecord).filter(MetricRecord.intervention_id == record_id).all()]
        passages = [p for p in db.query(PassageRecord).filter(PassageRecord.intervention_id == record_id).all()]
    finally:
        db.close()

    comps = rec.intervention_components or {}
    if not isinstance(comps, dict):
        comps = {}

    tier = rec.evidence_level or comps.get("evidence_tier") or "unknown"
    is_gold = _is_gold(tier)

    return {
        "implementation": {
            "id": rec.id,
            "title": rec.intervention_title,
            "tier": tier,
            "is_gold_asset": is_gold,
            "source_url": comps.get("source_url") or rec.source_id or "",
            "organization": {
                "name": rec.organization_name,
                "industry": rec.organization_industry or [],
                "geography": rec.organization_geography or [],
                "employee_count": rec.organization_employee_count,
                "anonymized": bool(rec.organization_anonymized),
            },
            "problem": {
                "statement": rec.problem_statement,
                "business_functions": rec.problem_business_function or [],
                "baseline_description": rec.problem_baseline_description,
            },
            "intervention": {
                "title": rec.intervention_title,
                "description": rec.intervention_description,
                "category": comps.get("intervention_category"),
                "workflow": comps.get("workflow"),
                "software": rec.intervention_software or [],
                "vendors": rec.intervention_vendors or [],
                "families": rec.intervention_families or [],
            },
            "deployment": {
                "result_status": rec.result_status,
                "pattern": rec.implementation_pattern or [],
                "partner": rec.implementation_partner or [],
                "rollout_strategy": rec.rollout_strategy,
                "governance_model": rec.governance_model,
                "change_management": rec.change_management,
                "training_approach": rec.training_approach,
                "adoption_approach": rec.adoption_approach,
                "pilot_structure": rec.pilot_structure,
            },
            "timeline": {
                "measurement_period_value": rec.intervention_measurement_period_value,
                "measurement_period_unit": rec.intervention_measurement_period_unit,
                "implementation_time_value": rec.intervention_implementation_time_value,
                "implementation_time_unit": rec.intervention_implementation_time_unit,
            },
            "outcomes": {
                "metrics": [
                    {
                        "name": m.metric_name,
                        "category": m.metric_category,
                        "percentage_change": m.percentage_change,
                        "absolute_change": m.absolute_change,
                        "baseline_value": m.baseline_value,
                        "post_value": m.post_value,
                        "unit": m.unit,
                        "reported_text": m.reported_text,
                    }
                    for m in metrics
                ],
                "sample_size": rec.sample_size,
                "has_baseline": bool(rec.has_baseline),
            },
            "risk_and_learning": {
                "lessons_learned": rec.lessons_learned or [],
                "success_factors": rec.success_factors or [],
                "risks": rec.risks or [],
                "implementation_challenges": rec.implementation_challenges or [],
                "failure_conditions": rec.failure_conditions or [],
                "limitations": rec.limitations or [],
            },
            "evidence_quality": {
                "evidence_level": tier,
                "richness": rec.implementation_richness,
                "independently_verified": bool(rec.independently_verified),
                "vendor_reported": bool(rec.vendor_reported),
                "implementation_provenance": rec.implementation_provenance,
                "outcome_provenance": rec.outcome_provenance,
                "passage_count": len(passages),
            },
            "sources": {
                "passages": [
                    {"section": p.section, "page": p.page_number, "text": p.passage_text[:600], "confidence": p.extraction_confidence}
                    for p in passages[:10]
                ],
            },
        }
    }