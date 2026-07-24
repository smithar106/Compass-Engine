import uuid
from datetime import datetime, timezone
from compass_collector.analysis.recommendation import recommend
from compass_collector.analysis.retrieval import get_negative_evidence
from compass_collector.api.evidence_tier import classify_tier_for_comparable
from compass_collector.api.schemas import (
    InvestigationRequest,
    RecommendationResponse,
    Recommendation,
    ComparableEvidence,
    NegativeEvidence,
    AlternativeConsidered,
    Confidence,
    EvidenceSummary,
    ProjectedImpact,
    Timeline,
)


def run_recommendation(req: InvestigationRequest) -> RecommendationResponse:
    workflow = req.workflow or _infer_workflow(req.business_function)
    business_function = req.business_function or "operations"
    industry = req.industry or "technology"
    employee_count = _parse_company_size(req.company_size)
    desired_outcome = req.desired_outcome or "efficiency"

    engine_result = recommend(
        workflow=workflow,
        business_function=business_function,
        industry=industry,
        employee_count=employee_count,
        desired_outcome=desired_outcome,
    )

    interventions = engine_result.get("recommended_interventions", [])
    ctx = engine_result.get("recommendation_context", {})
    why = engine_result.get("why", {})

    all_comparables: list[dict] = []
    for inv in interventions:
        for ex in inv.get("top_examples", []):
            all_comparables.append(ex)

    raw_negative = why.get("negative_evidence") or engine_result.get("negative_evidence", [])
    if isinstance(raw_negative, list):
        neg_list = raw_negative
    elif isinstance(raw_negative, int):
        neg_list = why.get("negative_evidence", []) if isinstance(why.get("negative_evidence"), list) else []

    recommendations = _build_recommendations(interventions, all_comparables, neg_list, ctx, why)

    run_id = str(uuid.uuid4())
    problem_profile = {
        "workflow": workflow,
        "business_function": business_function,
        "industry": industry,
        "company_size": req.company_size,
        "desired_outcome": desired_outcome,
        "problem_statement": req.problem_statement,
        "workflow_frequency": req.workflow_frequency,
        "people_involved": req.people_involved,
        "handoffs": req.handoffs,
        "current_tools": req.current_tools,
        "exception_rate": req.exception_rate,
        "budget_range": req.budget_range,
        "implementation_timeline": req.implementation_timeline,
        "business_risk": req.business_risk,
        "process_stability": req.process_stability,
        "previous_attempts": req.previous_attempts,
        "engine_version": "compass-recommendation-v2",
        "dataset_version": "v1",
    }

    overall_conf = engine_result.get("overall_confidence", {})

    return RecommendationResponse(
        recommendation_run_id=run_id,
        problem_profile=problem_profile,
        recommendations=recommendations,
        confidence_breakdown=overall_conf.get("breakdown", {}),
    )


def _build_recommendations(
    interventions: list,
    all_comparables: list,
    negative_evidence: list,
    ctx: dict,
    why: dict,
) -> list[Recommendation]:
    ranked: list[Recommendation] = []

    for i, inv in enumerate(interventions):
        if len(ranked) >= 3:
            break
        rank = len(ranked) + 1
        comp_score = inv.get("confidence", 50)

        tiered_comparables = _classify_comparables(inv.get("top_examples", []))
        gold = sum(1 for c in tiered_comparables if c.evidence_tier == "gold")
        silver = sum(1 for c in tiered_comparables if c.evidence_tier == "silver")
        bronze = sum(1 for c in tiered_comparables if c.evidence_tier == "bronze")
        total = len(tiered_comparables)
        failed = sum(1 for c in tiered_comparables if c.status in ("failed", "abandoned"))

        avg_evidence = _avg_evidence_score(tiered_comparables)
        overall_tier = _overall_tier(gold, silver, bronze)
        confidence_label, confidence_explanation = _confidence_label_and_explanation(comp_score, total, gold)
        impact, timeline = _build_impact_and_timeline(tiered_comparables, inv)

        rec = Recommendation(
            rank=rank,
            is_compass_choice=rank == 1,
            title=inv.get("family_name", "Recommendation"),
            summary=inv.get("description", "")[:300],
            intervention_category=inv.get("family_id", "unknown"),
            fit_score=round(comp_score / 10, 1),
            confidence=Confidence(score=round(comp_score / 100, 2), label=confidence_label, explanation=confidence_explanation),
            evidence_summary=EvidenceSummary(
                overall_tier=overall_tier, total_comparables=total,
                gold_count=gold, silver_count=silver, bronze_count=bronze,
                failed_comparables=failed, average_evidence_score=round(avg_evidence, 1),
            ),
            projected_impact=impact, timeline=timeline,
            why_it_ranked=_why_it_ranked(inv, rank, total, gold),
            comparables=tiered_comparables,
            negative_evidence=_build_negative_evidence(negative_evidence, inv),
            alternatives_considered=_build_alternatives(interventions, i),
            assumptions=_build_assumptions(inv), risks=_build_risks(inv),
        )
        ranked.append(rec)

    if not ranked:
        return [_placeholder_rec(1)]

    # Trim based on confidence gaps between adjacent recommendations
    if len(ranked) >= 2:
        gap_1_2 = ranked[0].confidence.score - ranked[1].confidence.score
        if gap_1_2 > 0.30:
            return [ranked[0]]

    if len(ranked) >= 3:
        gap_2_3 = ranked[1].confidence.score - ranked[2].confidence.score
        if gap_2_3 > 0.30:
            return ranked[:2]

    return ranked


def _classify_comparables(examples: list[dict]) -> list[ComparableEvidence]:
    result = []
    for ex in examples:
        tier = classify_tier_for_comparable(ex)
        if tier == "rejected":
            continue
        result.append(ComparableEvidence(
            organization=ex.get("organization", "Unknown"),
            industry="",
            workflow="",
            intervention=ex.get("intervention", ""),
            outcome="; ".join(ex.get("outcomes", [])),
            status=ex.get("status", "unknown"),
            similarity_score=ex.get("similarity", 0),
            evidence_score=ex.get("evidence_score", 50),
            evidence_tier=tier,
            supporting_passage=ex.get("summary", ""),
            source_title=ex.get("organization", ""),
            source_url="",
        ))
    return result


def _build_negative_evidence(neg_list: list, inv: dict) -> list[NegativeEvidence]:
    result = []
    for n in neg_list[:3]:
        result.append(NegativeEvidence(
            organization=n.get("organization", "Unknown"),
            intervention=n.get("intervention", ""),
            failure_reasons=n.get("failure_reasons", [])[:3],
            similarity_score=0,
        ))
    return result


def _build_alternatives(interventions: list, skip_idx: int) -> list[AlternativeConsidered]:
    alts = []
    for j, inv in enumerate(interventions):
        if j == skip_idx:
            continue
        if len(alts) >= 3:
            break
        alts.append(AlternativeConsidered(
            family=inv.get("family_name", ""),
            reason=f"{inv.get('comparable_count', 0)} comparable implementations, confidence {inv.get('confidence', 0)}%",
        ))
    return alts


def _build_impact_and_timeline(tiered_comparables: list, inv: dict) -> tuple[ProjectedImpact, Timeline]:
    impact_scores = []
    for c in tiered_comparables:
        if c.evidence_tier == "gold" and c.outcome:
            for part in c.outcome.split(";"):
                if "%" in part:
                    try:
                        num_str = part.split(":")[-1].strip().replace("%", "").replace("+", "").replace("-", "")
                        impact_scores.append(float(num_str))
                    except (ValueError, IndexError):
                        pass

    if impact_scores:
        low = round(min(impact_scores), 0)
        high = round(max(impact_scores), 0)
        return ProjectedImpact(
            label=f"{low:.0f}%–{high:.0f}% improvement",
            low=low,
            high=high,
            unit="%",
            methodology="Based on outcomes from gold-tier comparable implementations",
            is_sufficiently_supported=True,
        ), Timeline(low_weeks=8, high_weeks=16)

    if inv.get("comparable_count", 0) >= 3:
        return ProjectedImpact(
            label="Improvement expected (insufficient quantified data)",
            is_sufficiently_supported=False,
        ), Timeline(low_weeks=8, high_weeks=16)

    return ProjectedImpact(is_sufficiently_supported=False), Timeline(low_weeks=None, high_weeks=None)


def _why_it_ranked(inv: dict, rank: int, total_comparables: int, gold_count: int) -> list[str]:
    reasons = []
    if rank == 1:
        reasons.append(f"Highest confidence score ({inv.get('confidence', 0)}%) among all intervention families")
    else:
        reasons.append(f"Confidence score: {inv.get('confidence', 0)}%")
    reasons.append(f"{total_comparables} comparable implementations found")
    if gold_count > 0:
        reasons.append(f"{gold_count} gold-tier evidence sources")
    return reasons


def _build_assumptions(inv: dict) -> list[str]:
    assumptions = []
    count = inv.get("comparable_count", 0)
    if count < 5:
        assumptions.append("Limited comparable implementations available — outcomes may vary")
    if inv.get("confidence", 0) < 50:
        assumptions.append("Moderate confidence — additional validation recommended")
    return assumptions


def _build_risks(inv: dict) -> list[str]:
    risks = []
    if inv.get("comparable_count", 0) < 3:
        risks.append("Few comparable implementations — execution risk unknown")
    return risks


def _avg_evidence_score(comparables: list[ComparableEvidence]) -> float:
    if not comparables:
        return 0
    return sum(c.evidence_score for c in comparables) / len(comparables)


def _overall_tier(gold: int, silver: int, bronze: int) -> str:
    if gold >= 2:
        return "gold"
    if gold + silver >= 3:
        return "silver"
    return "bronze"


def _confidence_label_and_explanation(score: float, total: int, gold: int) -> tuple[str, str]:
    if score >= 70 and total >= 10 and gold >= 2:
        return "strong", f"Strong confidence based on {total} comparable implementations including {gold} gold-tier sources"
    if score >= 40 and total >= 3:
        return "moderate", f"Moderate confidence based on {total} comparable implementations"
    return "limited", f"Limited evidence available ({total} comparable implementations)"


def _placeholder_rec(rank: int) -> Recommendation:
    return Recommendation(
        rank=rank,
        is_compass_choice=rank == 1,
        title="Additional Recommendation",
        summary="Insufficient comparable evidence to generate a specific recommendation at this time.",
        intervention_category="unknown",
        fit_score=0,
        confidence=Confidence(score=0, label="limited", explanation="Insufficient evidence"),
        evidence_summary=EvidenceSummary(),
        projected_impact=ProjectedImpact(is_sufficiently_supported=False),
        timeline=Timeline(),
        why_it_ranked=["Insufficient comparable implementations to rank with confidence"],
    )


def _infer_workflow(business_function: str) -> str:
    mapping = {
        "sales": "lead_qualification",
        "marketing": "marketing_automation",
        "customer_success": "customer_health_scoring",
        "support": "ticketing",
        "finance": "invoice_processing",
        "product": "product_analytics",
        "engineering": "ci_cd",
        "human_resources": "onboarding",
        "hr": "onboarding",
        "people_hr": "onboarding",
        "legal": "contract_review",
        "operations": "process_automation",
    }
    return mapping.get(business_function.lower(), "process_automation")


def _parse_company_size(size_str: str) -> int | None:
    if not size_str:
        return None
    size_str = str(size_str).lower().strip()
    ranges = {
        "1-10": 5,
        "11-50": 30,
        "51-200": 125,
        "201-1000": 600,
        "1001-5000": 3000,
        "5001-10000": 7500,
        "10000+": 15000,
        "1-50": 25,
        "50-200": 125,
        "200-1000": 600,
        "1000-10000": 5000,
        "small": 50,
        "medium": 500,
        "large": 5000,
        "enterprise": 10000,
    }
    return ranges.get(size_str)
