from typing import Dict, List, Optional, Tuple
from compass_collector.api.schemas import (
    InvestigationRequest,
    ScoreBreakdown,
    ScoreComponent,
    ScoredInterventionResult,
    ComparableImplementationComparison,
)
from compass_collector.config.scoring_weights import get_scoring_config
from compass_collector.analysis.component_scoring import (
    compute_all_component_scores,
    compute_match_score,
    score_evidence_strength,
)


def _evidence_strength_label(candidate: dict) -> str:
    es = score_evidence_strength(candidate)
    if es.score >= 75:
        return "Strong"
    if es.score >= 50:
        return "Moderate"
    if es.score >= 25:
        return "Limited"
    return "Low"


def _difficulty_label(candidate: dict) -> str:
    families = candidate.get("intervention_families", [])
    families_lower = [f.lower() for f in families]
    if any("ai" in f for f in families_lower):
        return "High"
    if any("hybrid" in f for f in families_lower):
        return "High"
    if any("software" in f for f in families_lower):
        return "Medium to High"
    if any("process" in f for f in families_lower):
        return "Medium"
    if any("automation" in f for f in families_lower):
        return "Low to Medium"
    if any("staffing" in f for f in families_lower):
        return "Low"
    return "Medium"


def _timeframe_label(candidate: dict) -> str:
    duration = candidate.get("intervention_implementation_time_value")
    unit = candidate.get("intervention_implementation_time_unit", "")
    if duration:
        unit_display = unit if unit else "weeks"
        return f"~{duration:.0f} {unit_display}"
    families = candidate.get("intervention_families", [])
    families_lower = [f.lower() for f in families]
    if any("ai" in f for f in families_lower):
        return "8-24 weeks"
    if any("software" in f for f in families_lower):
        return "10-30 weeks"
    if any("automation" in f for f in families_lower):
        return "4-12 weeks"
    if any("process" in f for f in families_lower):
        return "6-20 weeks"
    if any("staffing" in f for f in families_lower):
        return "4-16 weeks"
    return "To be determined"


def _risks_from_candidate(candidate: dict) -> List[str]:
    risks = []
    if candidate.get("vendor_reported"):
        risks.append("Vendor-reported outcome — may overstate results")
    if candidate.get("result_status") in ("failed", "abandoned"):
        risks.append("Similar implementations have failed or been abandoned")
    families = candidate.get("intervention_families", [])
    families_lower = [f.lower() for f in families]
    if "ai" in families_lower:
        risks.append("Model quality depends on training data availability")
        risks.append("Requires ongoing monitoring and retuning")
    if any("automation" in f for f in families_lower):
        risks.append("Complex exceptions may still require manual review")
    if any("software" in f for f in families_lower):
        risks.append("Integration with existing systems may take longer than expected")
    if not risks:
        risks.append("Implementation risk depends on organizational readiness")
    return risks[:3]


def _advantages_from_candidate(candidate: dict) -> List[str]:
    families = candidate.get("intervention_families", [])
    families_lower = [f.lower() for f in families]
    if "ai" in families_lower:
        return ["Handles unstructured tasks", "Scales with volume", "Improves over time"]
    if any("automation" in f for f in families_lower):
        return ["Fast implementation", "Clear ROI from reduced manual effort", "Low technical risk"]
    if any("software" in f for f in families_lower):
        return ["Purpose-built functionality", "Vendor support", "Standardized workflows"]
    if any("process" in f for f in families_lower):
        return ["Addresses root causes", "No new technology required", "Builds org capability"]
    if any("staffing" in f for f in families_lower):
        return ["Flexible and reversible", "Directly addresses capacity", "Builds expertise"]
    return ["Proven approach", "Evidence-backed outcomes"]


def _tradeoffs_from_candidate(candidate: dict, rank: int) -> List[str]:
    families = candidate.get("intervention_families", [])
    families_lower = [f.lower() for f in families]
    if "ai" in families_lower:
        return ["Requires training data", "Needs ongoing monitoring", "Regulatory uncertainty"]
    if any("automation" in f for f in families_lower):
        return ["Requires structured processes", "Limited to rule-based tasks", "Exceptions need manual handling"]
    if any("software" in f for f in families_lower):
        return ["Vendor lock-in risk", "Integration complexity", "Requires change management"]
    if any("process" in f for f in families_lower):
        return ["Slower to implement", "Harder to measure ROI", "Requires stakeholder buy-in"]
    if any("staffing" in f for f in families_lower):
        return ["Hard to scale quickly", "Talent availability risk", "Higher ongoing cost"]
    return ["Requires careful implementation planning"]


def _select_comparables(
    candidate: dict,
    all_candidates: List[dict],
    assessment: InvestigationRequest,
    max_results: int = 3,
) -> List[ComparableImplementationComparison]:
    scored = []
    for c in all_candidates:
        if c.get("id") == candidate.get("id"):
            continue
        similarity = 0.0
        org = c.get("organization", "")
        if not org or org == "Unknown":
            continue
        wf = _workflow_overlap(
            c.get("problem_statement", ""),
            candidate.get("problem_statement", ""),
        )
        ind = _industry_overlap(
            c.get("organization_industry", []),
            assessment.industry,
        )
        similarity = wf * 0.5 + ind * 0.3
        if c.get("independently_verified"):
            similarity += 0.2
        scored.append((similarity, c))

    scored.sort(key=lambda x: -x[0])

    seen_sources = set()
    results = []
    for sim, c in scored:
        source = c.get("organization", "")
        if source in seen_sources:
            continue
        seen_sources.add(source)
        outcome = "; ".join(c.get("outcome_summaries", [])[:2]) or "Outcome documented"
        metric_name = ""
        metrics = c.get("metrics", [])
        if metrics:
            m = metrics[0]
            metric_name = m.get("metric_name", "")
            if m.get("percentage_change") is not None:
                metric_name += f": {m['percentage_change']:+.0f}%"
            elif m.get("absolute_change") is not None:
                metric_name += f": {m['absolute_change']:+.0f} {m.get('unit', '')}"

        results.append(ComparableImplementationComparison(
            organization_name=c.get("organization", "Unknown"),
            organization_type=c.get("organization_type", ""),
            company_size_category=c.get("organization_employee_band", ""),
            industry=", ".join(c.get("organization_industry", [])),
            problem_addressed=(c.get("problem_statement", "") or "")[:200],
            intervention_used=c.get("intervention_title", ""),
            documented_outcome=outcome,
            metric=metric_name,
            evidence_quality_score=c.get("evidence_score", 0),
            source_citation=c.get("organization", "Unknown"),
            comparability_explanation=(
                f"Similar workflow ({'direct' if sim > 0.6 else 'related'} match) "
                f"in {'matching' if sim > 0.3 else 'comparable'} organizational context"
            ),
        ))
        if len(results) >= max_results:
            break

    return results


def _workflow_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a = a.lower().strip().replace("_", " ").replace("-", " ")
    b = b.lower().strip().replace("_", " ").replace("-", " ")
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.7
    a_words = set(a.split())
    b_words = set(b.split())
    if a_words and b_words:
        overlap = len(a_words & b_words)
        total = len(a_words | b_words)
        if total > 0:
            return overlap / total
    return 0.0


def _industry_overlap(industries: List[str], target: str) -> float:
    if not industries or not target:
        return 0.0
    target = target.lower().strip()
    for ind in industries:
        ind = (ind or "").lower().strip()
        if target == ind:
            return 1.0
        if target in ind or ind in target:
            return 0.7
    return 0.0


def rank_interventions(
    candidates: List[dict],
    assessment: InvestigationRequest,
) -> Tuple[List[ScoredInterventionResult], Dict[str, float]]:
    config = get_scoring_config()
    weights = config.weights

    scored_results = []
    for c in candidates:
        components = compute_all_component_scores(c, assessment, candidates)
        match_score = compute_match_score(components, weights)
        scored_results.append((match_score, c, components))

    scored_results.sort(key=lambda x: -x[0])

    ranked = []
    used_ids = set()
    for match_score, candidate, components in scored_results:
        cid = candidate.get("id", "")
        if cid in used_ids:
            continue
        used_ids.add(cid)

        rank = len(ranked) + 1
        label = "recommended" if rank == 1 else "alternative"

        if rank > 1 and len(ranked) >= 1:
            prev_score = ranked[-1].match_score
            if abs(match_score - prev_score) < 5:
                ranked[-1].rationale += " These options are similarly matched."

        comparisons = _select_comparables(candidate, candidates, assessment)

        ranked.append(ScoredInterventionResult(
            intervention_id=cid,
            intervention_name=candidate.get("intervention_title", ""),
            rank=rank,
            label=label,
            match_score=match_score,
            score_breakdown=ScoreBreakdown(**components),
            expected_impact="; ".join(candidate.get("outcome_summaries", [])[:2]) or "Outcome data available",
            evidence_strength=_evidence_strength_label(candidate),
            implementation_difficulty=_difficulty_label(candidate),
            estimated_timeframe=_timeframe_label(candidate),
            top_risks=_risks_from_candidate(candidate),
            key_advantages=_advantages_from_candidate(candidate),
            key_tradeoffs=_tradeoffs_from_candidate(candidate, rank),
            comparable_implementations=comparisons,
            rationale=_build_rationale(candidate, match_score, components, rank),
        ))

        if len(ranked) >= 3:
            break

    return ranked, weights


def _build_rationale(
    candidate: dict,
    match_score: float,
    components: dict,
    rank: int,
) -> str:
    parts = []
    top_component = max(components.items(), key=lambda x: x[1].score)
    parts.append(f"Match score {match_score:.0f}/100")
    parts.append(f"Strongest dimension: {top_component[0].replace('_', ' ')} ({top_component[1].score:.0f}/100)")
    if rank == 1:
        parts.append("Best overall fit across all scoring dimensions")
    else:
        parts.append("Credible alternative with distinct strengths")
    return ". ".join(parts)
