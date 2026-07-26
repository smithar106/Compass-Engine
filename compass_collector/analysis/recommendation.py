"""Recommendation engine — connects recommendations to evidence via comparable implementations."""

from typing import Optional
from compass_collector.analysis.retrieval import (
    ImplementationQuery,
    find_comparable_implementations,
    get_negative_evidence,
    get_evidence_for_recommendation,
)
from compass_collector.analysis.evidence_score import compute_evidence_score
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.database import get_session


# Core intervention families for recommendations
RECOMMENDATION_FAMILIES = [
    {
        "id": "AI",
        "name": "AI Implementation",
        "subtypes": ["generative_ai", "predictive_ai", "ai_assisted_work", "autonomous_ai", "human_in_the_loop_ai"],
        "description": "Artificial intelligence solutions including machine learning, NLP, computer vision, and generative AI",
    },
    {
        "id": "Software",
        "name": "Software Implementation",
        "subtypes": ["new_software_implementation", "existing_software_optimization", "cloud_migration", "crm_implementation", "erp_implementation"],
        "description": "New software adoption, platform migration, or optimization of existing systems",
    },
    {
        "id": "Workflow_Automation",
        "name": "Workflow Automation",
        "subtypes": ["rpa", "workflow_automation", "rules_based_automation", "robotic_process_automation", "workflow_simplification"],
        "description": "Automation of repetitive processes using RPA, workflow tools, or rules-based systems",
    },
    {
        "id": "Process_Redesign",
        "name": "Process Redesign",
        "subtypes": ["process_redesign", "lean", "business_process_reengineering", "organizational_restructuring"],
        "description": "Fundamental redesign of operational processes to improve efficiency and outcomes",
    },
    {
        "id": "Staffing",
        "name": "Staffing Change",
        "subtypes": ["staffing_increases", "staffing_reallocation", "outsourcing", "training", "managed_services"],
        "description": "Changes to team structure, hiring, training, or outsourcing arrangements",
    },
    {
        "id": "Hybrid",
        "name": "Hybrid Intervention",
        "subtypes": ["hybrid_combination", "ai_human_collaboration", "augmented_workflow"],
        "description": "Combination of multiple intervention types (e.g., AI + human review, automation + process redesign)",
    },
]


def get_family_for_subcategory(subcategory: str) -> Optional[str]:
    """Map an intervention subcategory to its core family."""
    sub = subcategory.lower().replace(" ", "_")
    for family in RECOMMENDATION_FAMILIES:
        if sub in [s.lower() for s in family["subtypes"]]:
            return family["id"]
        if sub == family["id"].lower():
            return family["id"]
    return None


def recommend(
    workflow: str,
    business_function: str,
    industry: str = "",
    employee_count: Optional[int] = None,
    desired_outcome: str = "",
) -> dict:
    """Generate a recommendation backed by evidence from comparable implementations.

    This is the main entry point for Compass recommendations.
    """
    evidence = get_evidence_for_recommendation(
        workflow=workflow,
        business_function=business_function,
        industry=industry,
        employee_count=employee_count,
        desired_outcome=desired_outcome,
    )

    comparable = evidence["comparable_implementations"]

    # Determine best intervention family from evidence
    family_counts = {}
    for r in comparable["results"]:
        for f in r.get("intervention_families", []):
            family = get_family_for_subcategory(f)
            if family:
                family_counts[family] = family_counts.get(family, 0) + 1

    # Rank families by frequency among top results
    ranked_families = sorted(family_counts.items(), key=lambda x: -x[1])

    # Build recommended interventions
    recommended = []
    for family_id, count in ranked_families:
        family_info = next((f for f in RECOMMENDATION_FAMILIES if f["id"] == family_id), None)
        if not family_info:
            continue

        # Find top results for this family
        family_results = [r for r in comparable["results"] if family_id in
                         [get_family_for_subcategory(f) for f in r.get("intervention_families", [])]]

        top_results = family_results[:3]
        top_summaries = []
        for r in top_results:
            top_summaries.append({
                "id": r.get("id", ""),
                "organization": r.get("organization", "Unknown"),
                "intervention": r.get("intervention", ""),
                "intervention_families": r.get("intervention_families", []),
                "summary": r.get("summary", ""),
                "outcome_summaries": r.get("outcome_summaries", []),
                "outcomes": r.get("outcome_summaries", []),
                "similarity": r.get("similarity_score", 0),
                "similarity_score": r.get("similarity_score", 0),
                "similarity_breakdown": r.get("similarity_breakdown", {}),
                "employee_count": r.get("employee_count"),
                "status": r.get("status", "unknown"),
                "vendor_reported": r.get("vendor_reported", False),
                "independently_verified": r.get("independently_verified", False),
                "negatives": r.get("negatives", []),
                "evidence_score": r.get("evidence_score", 50),
                "cost_savings": r.get("cost_savings"),
                "implementation_time": r.get("implementation_time"),
            })

        recommended.append({
            "family_id": family_id,
            "family_name": family_info["name"],
            "description": family_info["description"],
            "confidence": _calculate_confidence(comparable, count, family_id),
            "comparable_count": count,
            "top_examples": top_summaries,
            "evidence_score": comparable.get("average_evidence_score", 0),
        })

    # Calculate overall confidence
    overall_confidence = _calculate_overall_confidence(comparable, evidence["negative_evidence"])

    return {
        "recommendation_context": evidence["recommendation_context"],
        "recommended_interventions": recommended,
        "overall_confidence": overall_confidence,
        "evidence_summary": comparable["confidence_summary"],
        "why": _build_why_panel(evidence, recommended, overall_confidence),
        "negative_evidence_count": len(evidence["negative_evidence"]),
    }


def _calculate_confidence(comparable: dict, family_count: int, family_id: str) -> int:
    """Calculate confidence score (0-100) for a specific intervention family.

    Requires outcome measurement for strong confidence.
    Penalizes adoption-only evidence (tool deployed without measured business impact).
    """
    score = 0

    # Base: number of comparable implementations
    total = comparable["total_found"]
    if total >= 50:
        score += 20
    elif total >= 20:
        score += 15
    elif total >= 10:
        score += 10
    elif total >= 5:
        score += 5
    else:
        score += 2

    # Family-specific count bonus
    if family_count >= 10:
        score += 10
    elif family_count >= 5:
        score += 8
    elif family_count >= 3:
        score += 5
    elif family_count >= 1:
        score += 3

    # Outcome measurement premium - the key differentiator
    # Strong confidence requires measurable business outcomes, not just adoption
    results = comparable.get("results", [])
    has_outcome_measurement = sum(1 for r in results if r.get("outcome_summaries"))
    has_quantified = sum(1 for r in results if any(
        "%" in s or "$" in s
        for s in r.get("outcome_summaries", [])
    ))
    has_baseline = sum(1 for r in results if r.get("cost_savings") or r.get("implementation_time"))

    if has_outcome_measurement >= 5 and has_quantified >= 3:
        score += 25  # Strong: multiple outcome-measured implementations
    elif has_outcome_measurement >= 3 and has_quantified >= 1:
        score += 15  # Moderate: some outcome data
    elif has_outcome_measurement >= 1:
        score += 5   # Weak: at least one outcome mentioned
    else:
        score -= 10  # Penalty: adoption-only, no outcome data

    # Outcome consistency bonus
    successful = comparable["status_breakdown"].get("successful", 0)
    if total > 0 and successful / total > 0.5:
        score += 10
    elif total > 0 and successful / total > 0.3:
        score += 5

    # Evidence quality bonus
    avg_evidence = comparable.get("average_evidence_score", 50)
    if avg_evidence >= 80:
        score += 10
    elif avg_evidence >= 60:
        score += 5
    elif avg_evidence >= 40:
        score += 2

    # Unique org diversity
    orgs = comparable["unique_organizations"]
    if orgs >= 10:
        score += 5
    elif orgs >= 5:
        score += 3

    # Negative evidence penalty
    failed = comparable["negative_evidence_count"]
    if failed > 0 and family_count > 0 and total > 0:
        ratio = failed / total
        if ratio > 0.5:
            score -= 20
        elif ratio > 0.3:
            score -= 10
        elif ratio > 0.1:
            score -= 5

    # Multiple source types bonus
    if comparable.get("status_breakdown"):
        non_vendor_count = sum(1 for r in comparable["results"][:10] if not r.get("vendor_reported"))
        if non_vendor_count >= 3:
            score += 8
        elif non_vendor_count >= 1:
            score += 3

    # Baseline/documentation bonus
    if has_baseline >= 3:
        score += 5

    return max(0, min(100, score))


def _calculate_overall_confidence(comparable: dict, negative_evidence: list) -> dict:
    """Calculate overall confidence score with breakdown.

    The goal is not to track AI adoption. It is to identify interventions
    that create measurable business value."""

    results = comparable.get("results", [])
    has_outcome = sum(1 for r in results if r.get("outcome_summaries"))
    has_quantified = sum(1 for r in results if any(
        "%" in s or "$" in s
        for s in r.get("outcome_summaries", [])
    ))
    has_baseline = sum(1 for r in results if r.get("cost_savings") or r.get("implementation_time"))

    base_score = 30

    # Volume factor (reduced weight - volume alone is not enough)
    total = comparable["total_found"]
    if total >= 100:
        base_score += 5
    elif total >= 50:
        base_score += 3
    elif total >= 20:
        base_score += 2

    # Outcome measurement factor (the key differentiator)
    if has_outcome >= 10 and has_quantified >= 5:
        base_score += 25
    elif has_outcome >= 5 and has_quantified >= 3:
        base_score += 20
    elif has_outcome >= 3 and has_quantified >= 1:
        base_score += 10
    elif has_outcome >= 1:
        base_score += 3
    else:
        base_score -= 10

    # Org diversity
    orgs = comparable["unique_organizations"]
    if orgs >= 20:
        base_score += 5
    elif orgs >= 10:
        base_score += 3

    # Outcome consistency
    successful = comparable["status_breakdown"].get("successful", 0)
    if total > 0 and successful / total > 0.5:
        base_score += 8

    # Evidence quality
    avg_evidence = comparable.get("average_evidence_score", 50)
    if avg_evidence >= 80:
        base_score += 7
    elif avg_evidence >= 60:
        base_score += 3

    # Baseline/documentation bonus
    if has_baseline >= 3:
        base_score += 5

    # Negative evidence penalty
    if negative_evidence:
        base_score -= min(15, len(negative_evidence) * 3)

    base_score = max(0, min(100, base_score))

    return {
        "score": base_score,
        "breakdown": {
            "comparable_implementations": comparable["total_found"],
            "unique_organizations": comparable["unique_organizations"],
            "average_evidence_score": comparable.get("average_evidence_score", 0),
            "successful_implementations": comparable["status_breakdown"].get("successful", 0),
            "negative_implementations": comparable["negative_evidence_count"],
            "outcome_measured_implementations": has_outcome,
            "quantified_outcome_implementations": has_quantified,
        },
        "summary": f"Based on {comparable['total_found']} comparable implementations across {comparable['unique_organizations']} organizations",
    }


def _build_why_panel(evidence: dict, recommended: list, confidence: dict) -> dict:
    """Build the 'Why?' panel — the heart of Compass."""
    comparable = evidence["comparable_implementations"]
    negative = evidence["negative_evidence"]

    results = comparable.get("results", [])
    has_outcome = sum(1 for r in results if r.get("outcome_summaries"))
    has_quantified = sum(1 for r in results if any(
        "%" in s or "$" in s
        for s in r.get("outcome_summaries", [])
    ))

    why = {
        "why_this_recommendation": _generate_why_summary(comparable, recommended, confidence),
        "compass_position": _generate_compass_position(has_outcome, has_quantified, comparable["total_found"]),
        "comparable_implementations": {
            "total": comparable["total_found"],
            "unique_organizations": comparable["unique_organizations"],
            "status_breakdown": comparable["status_breakdown"],
            "top_results": [
                {
                    "organization": r["organization"],
                    "intervention": r["intervention"],
                    "outcome": (r.get("outcome_summaries") or [])[0] if (r.get("outcome_summaries") or []) else "",
                    "similarity": r["similarity_score"],
                    "status": r["status"],
                }
                for r in comparable["results"][:5]
            ],
        },
        "expected_outcomes": _expected_outcomes(comparable),
        "alternative_interventions_considered": [
            {"family": r["family_name"], "reason": f"{r['comparable_count']} comparable implementations, confidence {r['confidence']}%"}
            for r in recommended[:4]
        ],
        "negative_evidence": [
            {
                "organization": n["organization"],
                "intervention": n["intervention"],
                "failure_reasons": n["failure_reasons"][:2],
            }
            for n in negative[:3]
        ] if negative else None,
        "confidence_methodology": {
            "overall_confidence": confidence["score"],
            "factors": confidence["breakdown"],
        },
    }

    return why


def _generate_compass_position(has_outcome: int, has_quantified: int, total: int) -> str:
    """Generate Compass's differentiating position statement."""
    if has_outcome >= 5 and has_quantified >= 3:
        return (
            "Compass helps organizations distinguish AI activity from AI impact. "
            f"Of {total} comparable implementations, {has_outcome} measured specific business outcomes "
            f"and {has_quantified} reported quantified results. These recommendations are based on "
            "interventions that created measurable business value — not just tool adoption."
        )
    if has_outcome >= 1:
        return (
            "Compass helps organizations distinguish AI activity from AI impact. "
            f"While {total} comparable implementations were found, only {has_outcome} documented "
            "measurable business outcomes. Recommendations reflect real-world evidence, "
            "prioritizing interventions with observed business impact over mere adoption."
        )
    return (
        "Compass helps organizations distinguish AI activity from AI impact. "
        f"Most of the {total} comparable implementations found document tool adoption rather than "
        "measured business outcomes. Confidence is limited accordingly. "
        "The goal is not to increase AI usage — it is to identify changes that create measurable business value."
    )


def _generate_why_summary(comparable: dict, recommended: list, confidence: dict) -> str:
    """Generate a concise 'Why' explanation."""
    parts = []

    # Lead with volume
    parts.append(f"Compass recommends this intervention based on {comparable['total_found']} comparable implementations across {comparable['unique_organizations']} independent organizations.")

    # Add top recommendation reasoning
    if recommended:
        top = recommended[0]
        parts.append(f"The strongest evidence supports **{top['family_name']}** ({top['confidence']}% confidence), with {top['comparable_count']} comparable implementations achieving consistent measured outcomes.")

    # Add outcome note
    successful = comparable["status_breakdown"].get("successful", 0)
    if successful > comparable["total_found"] * 0.5:
        parts.append(f"Over half of comparable implementations reported positive outcomes.")
    elif successful > comparable["total_found"] * 0.3:
        parts.append(f"A significant portion of comparable implementations reported positive outcomes.")

    # Add negative evidence note
    failed = comparable["negative_evidence_count"]
    if failed > 0:
        parts.append(f"**{failed} similar implementation{'s' if failed > 1 else ''} failed or {'were' if failed > 1 else 'was'} abandoned — those lessons are included in this analysis.")

    # Add alternatives
    if len(recommended) > 1:
        alts = [r["family_name"] for r in recommended[1:4]]
        parts.append(f"Alternative approaches considered: {' | '.join(alts)}.")

    return " ".join(parts)


def _expected_outcomes(comparable: dict) -> list[dict]:
    """Aggregate expected outcomes from comparable implementations."""
    outcome_counts = {}
    for r in comparable["results"]:
        for s in r.get("outcome_summaries", []):
            key = s.split(":")[0].strip() if ":" in s else s[:30]
            if key not in outcome_counts:
                outcome_counts[key] = {"examples": [], "count": 0}
            outcome_counts[key]["count"] += 1
            if len(outcome_counts[key]["examples"]) < 3:
                outcome_counts[key]["examples"].append({
                    "organization": r["organization"],
                    "detail": s,
                })

    sorted_outcomes = sorted(outcome_counts.items(), key=lambda x: -x[1]["count"])
    return [
        {
            "metric": metric,
            "occurrences": data["count"],
            "examples": data["examples"],
        }
        for metric, data in sorted_outcomes[:5]
    ]


def get_recommendation(evidence: dict) -> dict:
    """Convert a comparable implementation query into a structured recommendation.
    This is the main output for the Compass recommendation API."""
    pass
