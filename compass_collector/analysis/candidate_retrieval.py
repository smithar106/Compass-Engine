from typing import Optional
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, DuplicateRelationship
from compass_collector.api.schemas import InvestigationRequest
from compass_collector.analysis.retrieval import (
    ImplementationQuery,
    compute_similarity,
    _employee_count_to_band,
    _get_components,
    SIMILARITY_WEIGHTS,
)

# ── Constraint → relevant intervention families ──
# Determines which families are plausible enough to retrieve evidence for.
_CONSTRAINT_FAMILIES: dict[str, list[str]] = {
    "capacity": ["Staffing", "AI", "Workflow_Automation", "Hybrid", "Process_Redesign", "Software"],
    "errors":    ["Workflow_Automation", "AI", "Hybrid", "Software", "Process_Redesign"],
    "speed":     ["Workflow_Automation", "AI", "Software", "Hybrid", "Process_Redesign", "Staffing"],
    "quality":   ["AI", "Software", "Hybrid", "Process_Redesign", "Workflow_Automation"],
    "cost":      ["Workflow_Automation", "AI", "Hybrid", "Software", "Process_Redesign"],
    "visibility":["Software", "AI", "Process_Redesign", "Workflow_Automation"],
    "compliance":["Software", "Workflow_Automation", "Hybrid", "Process_Redesign", "AI"],
}


def _constraint_families(constraint: str) -> Optional[list[str]]:
    return _CONSTRAINT_FAMILIES.get(constraint)


def _sql_comparable_candidates(
    session,
    business_function: str = "",
    constraint: str = "",
    duplicate_source_ids: set = None,
    max_candidates: int = 2000,
) -> list[InterventionRecord]:
    """Stage 1: SQL pre-filter to reduce 53K→500–2000 records using indexed
    fields before Python relevance scoring.

    Uses LIKE on JSON-array intervention_families and problem_business_function
    for filtering. These are approximate (no JSON parsing overhead) — the Python
    similarity scorer does the precise matching.
    """
    from sqlalchemy import or_

    query = session.query(InterventionRecord)

    # Governance gate (migration 2026-08-14): only published evidence is
    # retrievable for recommendations. Legacy published (verification_status=legacy)
    # and claim-verified published both pass. Staging/quarantined/rejected excluded.
    query = query.filter(InterventionRecord.publication_status == "published")

    # Hard filter: must have intervention families
    query = query.filter(InterventionRecord.intervention_families.isnot(None))
    query = query.filter(InterventionRecord.intervention_families != "[]")

    # Build family-match conditions from constraint
    families = _constraint_families(constraint) if constraint else None
    family_conditions = []
    if families:
        for fam in families:
            family_conditions.append(
                InterventionRecord.intervention_families.contains(fam)
            )

    # Build business-function condition
    bf_condition = None
    if business_function:
        bf_condition = InterventionRecord.problem_business_function.contains(
            business_function
        )

    if family_conditions and bf_condition is not None:
        query = query.filter(or_(bf_condition, *family_conditions))
    elif family_conditions:
        query = query.filter(or_(*family_conditions))
    elif bf_condition is not None:
        query = query.filter(bf_condition)

    # Exclude known duplicates
    if duplicate_source_ids and len(duplicate_source_ids) > 0:
        query = query.filter(
            ~InterventionRecord.source_id.in_(list(duplicate_source_ids)[:5000])
        )

    records = query.limit(max_candidates).all()
    return records


def _parse_company_size(size_str: str) -> Optional[int]:
    if not size_str:
        return None
    size_str = size_str.strip().lower().replace(",", "").replace("+", "")
    try:
        return int(size_str)
    except ValueError:
        pass
    mapping = {
        "startup": 10, "small": 50, "medium": 500, "large": 5000, "enterprise": 10000,
    }
    return mapping.get(size_str)


def _record_to_dict(rec: InterventionRecord, metrics: list[MetricRecord], similarity: dict) -> dict:
    comps = _get_components(rec)
    outcome_summaries = []
    for m in metrics:
        if m.percentage_change is not None:
            outcome_summaries.append(f"{m.metric_name}: {m.percentage_change:+.0f}%")
        elif m.absolute_change is not None:
            outcome_summaries.append(f"{m.metric_name}: {m.absolute_change:+.0f} {m.unit or ''}")

    org_norm = rec.organization_normalized or {}
    primary = org_norm.get("primary_industry") or {}

    return {
        "id": rec.id,
        "organization": rec.organization_name or "",
        "organization_anonymized": rec.organization_anonymized,
        "organization_type": rec.organization_type or "",
        "organization_industry": rec.organization_industry or [],
        "organization_geography": rec.organization_geography or [],
        "organization_employee_count": rec.organization_employee_count,
        "organization_employee_band": _employee_count_to_band(rec.organization_employee_count),
        "organization_normalized": org_norm,
        "canonical_industry": primary.get("value", ""),
        "industry_subsector": primary.get("subsector", ""),
        "broader_industry": primary.get("broader", ""),
        "problem_statement": (rec.problem_statement or "")[:300],
        "problem_business_function": rec.problem_business_function or [],
        "problem_categories": rec.problem_categories or [],
        "intervention_title": rec.intervention_title or "",
        "intervention_families": rec.intervention_families or [],
        "intervention_description": (rec.intervention_description or "")[:500],
        "intervention_components": comps,
        "intervention_software": rec.intervention_software or [],
        "intervention_vendors": rec.intervention_vendors or [],
        "intervention_teams_involved": rec.intervention_teams_involved or [],
        "intervention_implementation_cost": rec.intervention_implementation_cost,
        "intervention_implementation_cost_currency": rec.intervention_implementation_cost_currency or "",
        "intervention_implementation_time_value": rec.intervention_implementation_time_value,
        "intervention_implementation_time_unit": rec.intervention_implementation_time_unit or "",
        "intervention_human_review_required": rec.intervention_human_review_required,
        "intervention_pilot_used": rec.intervention_pilot_used,
        "result_status": rec.result_status or "unknown",
        "success_factors": rec.success_factors or [],
        "failure_conditions": rec.failure_conditions or [],
        "implementation_challenges": rec.implementation_challenges or [],
        "risks": rec.risks or [],
        "limitations": rec.limitations or [],
        "has_baseline": rec.has_baseline,
        "has_post_measurement": rec.has_post_measurement,
        "has_control_group": rec.has_control_group,
        "sample_size": rec.sample_size,
        "measurement_method": rec.measurement_method or "",
        "independently_verified": rec.independently_verified,
        "vendor_reported": rec.vendor_reported,
        "metrics": [
            {
                "id": m.id,
                "metric_name": m.metric_name or "",
                "metric_category": m.metric_category or "",
                "baseline_value": m.baseline_value,
                "post_value": m.post_value,
                "absolute_change": m.absolute_change,
                "percentage_change": m.percentage_change,
                "unit": m.unit or "",
            }
            for m in metrics
        ],
        "outcome_summaries": outcome_summaries,
        "evidence_score": _compute_evidence_score(rec, metrics),
        "similarity_score": round(similarity["total"] * 100),
        "similarity_breakdown": similarity["components"],
        "result_statuses": [rec.result_status],
    }


def _compute_evidence_score(rec: InterventionRecord, metrics: list[MetricRecord]) -> float:
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


def _load_duplicate_ids(session) -> set:
    rels = session.query(DuplicateRelationship).all()
    dup_ids = set()
    for r in rels:
        dup_ids.add(r.source_a_id)
        dup_ids.add(r.source_b_id)
    return dup_ids


def retrieve_candidates(
    assessment: InvestigationRequest,
    max_candidates: int = 50,
    org_profile: Optional[dict] = None,
) -> list[dict]:
    """Retrieve comparable implementation candidates.

    Stage 1 — SQL pre-filter (53K → 500–2000):
        Filters by intervention families (from constraint) and business function
        using LIKE on JSON-array columns, plus duplicate exclusion.

    Stage 2 — Python relevance scoring:
        Runs the context-aware or legacy similarity computation on the
        filtered candidate pool.

    Stage 3 — Diversify:
        Deduplicates by organization name and selects the top N.
    """
    from compass_collector.analysis.context_retrieval import (
        ContextQuery,
        compute_context_similarity,
    )

    use_context = bool(org_profile or assessment.industry or assessment.geography or assessment.company_size)
    context_query = ContextQuery.from_profile(org_profile, assessment) if use_context else None
    employee_count = _parse_company_size(assessment.company_size)
    query = ImplementationQuery(
        workflow=assessment.workflow or assessment.problem_statement,
        business_function=assessment.business_function,
        industry=assessment.industry,
        employee_count=employee_count,
        desired_outcome=assessment.desired_outcome,
        max_results=max_candidates * 2,
    )

    session = get_session()
    try:
        duplicate_source_ids = _load_duplicate_ids(session)

        constraint = getattr(assessment, 'constraint', '') or ''
        records = _sql_comparable_candidates(
            session,
            business_function=assessment.business_function or "",
            constraint=constraint,
            duplicate_source_ids=duplicate_source_ids,
            max_candidates=2000,
        )

        scored = []
        # Batch-load all metrics for the filtered records in a single query
        record_ids = [r.id for r in records]
        metrics_map: dict = {}
        if record_ids:
            # Use IN query with chunking for very large candidate sets
            for chunk_start in range(0, len(record_ids), 500):
                chunk = record_ids[chunk_start:chunk_start + 500]
                for m in session.query(MetricRecord).filter(
                    MetricRecord.intervention_id.in_(chunk)
                ).all():
                    metrics_map.setdefault(m.intervention_id, []).append(m)

        for rec in records:
            if rec.intervention_families is None or len(rec.intervention_families) == 0:
                continue
            metrics = metrics_map.get(rec.id, [])
            has_claim = bool(metrics) or bool(rec.outcome_summaries if hasattr(rec, 'outcome_summaries') else False)
            if not has_claim and not rec.intervention_description:
                continue
            if context_query is not None:
                fit = compute_context_similarity(context_query, rec, metrics)
                total = fit.total
                components = fit.to_dict()["factors"]
            else:
                similarity = compute_similarity(query, rec, metrics)
                total = similarity["total"]
                components = similarity["components"]
            if total == 0:
                continue
            scored.append((total, rec, metrics, components))

        scored.sort(key=lambda x: -x[0])

        seen_orgs = set()
        candidates = []
        for sim_score, rec, metrics, components in scored:
            org = (rec.organization_name or "").lower()
            if org and org in seen_orgs:
                continue
            seen_orgs.add(org)
            candidate = _record_to_dict(rec, metrics, {"total": sim_score, "components": components})
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break

        if len(candidates) < 5:
            for sim_score, rec, metrics, components in scored[len(candidates):]:
                candidate_ids = {c["id"] for c in candidates}
                if rec.id not in candidate_ids:
                    candidates.append(_record_to_dict(rec, metrics, {"total": sim_score, "components": components}))
                    if len(candidates) >= max_candidates:
                        break

        return candidates

    finally:
        session.close()
