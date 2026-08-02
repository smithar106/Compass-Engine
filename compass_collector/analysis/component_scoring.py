from typing import Dict, List, Optional, Tuple
from compass_collector.api.schemas import InvestigationRequest, ScoreComponent
from compass_collector.config.scoring_weights import DEFAULT_SCORING_WEIGHTS


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


def _industry_overlap(industries: List[str], target_industry: str) -> float:
    if not industries or not target_industry:
        return 0.0
    target = target_industry.lower().strip()
    for ind in industries:
        ind = (ind or "").lower().strip()
        if target == ind:
            return 1.0
        if target in ind or ind in target:
            return 0.7
    return 0.0


def _industry_overlap_canonical(candidate: dict, target_industry: str) -> float:
    """Industry overlap using the canonical taxonomy.

    Compares canonical industry keys (and subsector) so 'Banking', 'FinTech',
    and 'Financial Services' all match, instead of raw-string overlap.
    """
    if not target_industry:
        return 0.0
    from compass_collector.organization.taxonomy import normalize_industry

    t = normalize_industry(str(target_industry))
    if not t.mapped:
        return _industry_overlap(candidate.get("organization_industry", []), target_industry)

    candidate_keys: list[str] = []
    if candidate.get("canonical_industry"):
        candidate_keys.append(str(candidate["canonical_industry"]))
    for raw in candidate.get("organization_industry", []) or []:
        n = normalize_industry(str(raw))
        if n.mapped and n.canonical not in candidate_keys:
            candidate_keys.append(n.canonical)

    if not candidate_keys:
        return 0.0
    if t.canonical in candidate_keys:
        # subsector match is stronger than same-broader-industry
        cand_sub = str(candidate.get("industry_subsector") or "")
        if t.subsector and cand_sub and t.subsector == cand_sub:
            return 1.0
        return 0.8
    return 0.3


def _employee_band_distance(candidate_count: Optional[int], assessment_size: Optional[int]) -> float:
    if candidate_count is None or assessment_size is None:
        return 0.0
    bands = [(0, 10), (10, 50), (50, 200), (200, 1000), (1000, 10000), (10000, None)]
    def band_index(count):
        for i, (lo, hi) in enumerate(bands):
            if hi is None and count >= lo:
                return i
            if lo <= count < hi:
                return i
        return -1
    ci = band_index(candidate_count)
    ai = band_index(assessment_size)
    if ci == -1 or ai == -1:
        return 0.0
    dist = abs(ci - ai)
    if dist == 0:
        return 1.0
    if dist == 1:
        return 0.5
    if dist == 2:
        return 0.2
    return 0.0


def _parse_company_size(size_str: str) -> Optional[int]:
    if not size_str:
        return None
    size_str = size_str.strip().lower().replace(",", "").replace("+", "")
    try:
        return int(size_str)
    except ValueError:
        pass
    mapping = {"startup": 10, "small": 50, "medium": 500, "large": 5000, "enterprise": 10000}
    return mapping.get(size_str)


def _goal_categories() -> Dict[str, List[str]]:
    return {
        "cost_reduction": ["cost", "cost_savings", "cost_reduction", "savings", "spend"],
        "time_savings": ["time", "cycle_time", "processing_time", "response_time", "resolution_time", "efficiency"],
        "revenue_growth": ["revenue", "revenue_increase", "growth", "conversion"],
        "quality_improvement": ["quality", "error_rate", "defect_rate", "accuracy", "compliance"],
        "risk_reduction": ["risk", "incident", "compliance", "security", "fraud"],
        "customer_satisfaction": ["satisfaction", "csat", "nps", "customer"],
        "employee_productivity": ["productivity", "throughput", "capacity", "output", "utilization"],
    }


def _match_goal(desired_outcome: str, metrics: List[dict]) -> Tuple[float, str]:
    if not desired_outcome or not metrics:
        return 0.0, "No goal or metrics available for comparison"
    goal = desired_outcome.lower().strip()
    categories = _goal_categories()
    matched_cats = set()
    for cat, keywords in categories.items():
        for kw in keywords:
            if kw in goal or goal in kw:
                matched_cats.add(cat)

    if not matched_cats:
        return 0.0, "Goal category not recognized in available outcome data"

    for m in metrics:
        mname = (m.get("metric_name") or m.get("name") or "").lower()
        mcat = (m.get("metric_category") or "").lower()
        for cat in matched_cats:
            cat_keywords = categories[cat]
            if any(kw in mname or kw in mcat for kw in cat_keywords):
                if m.get("percentage_change") is not None or m.get("absolute_change") is not None:
                    return 0.9, f"Metrics directly aligned with {cat.replace('_', ' ')}"
                return 0.6, f"Outcome category matches {cat.replace('_', ' ')} but lacks quantified change"

    return 0.3, "Partial alignment with goal category"


def score_problem_alignment(candidate: dict, assessment: InvestigationRequest) -> ScoreComponent:
    wf_score = _workflow_overlap(
        assessment.workflow or assessment.problem_statement,
        candidate.get("problem_statement", ""),
    )
    bf_score = _workflow_overlap(
        assessment.business_function,
        " ".join(candidate.get("problem_business_function", [])),
    )
    raw = max(wf_score, bf_score) * 100
    raw = max(0, min(100, raw))
    reason = (
        f"Directly addresses {assessment.workflow or assessment.problem_statement[:50]}"
        if raw >= 70
        else f"Related to {assessment.business_function or 'assessed'} workflow"
        if raw >= 40
        else "Partial alignment with assessed problem area"
    )
    return ScoreComponent(score=round(raw, 1), weight=0.0, reason=reason)


def score_organizational_similarity(candidate: dict, assessment: InvestigationRequest) -> ScoreComponent:
    org_type = candidate.get("organization_type", "")
    industries = candidate.get("organization_industry", [])
    emp_count = candidate.get("organization_employee_count")
    geography = candidate.get("organization_geography", [])
    assessment_size = _parse_company_size(assessment.company_size)

    components = []
    total_weight = 0.0

    org_sim = 0.5 if org_type and org_type == assessment.company_size else 0.0
    components.append(org_sim * 0.25)
    total_weight += 0.25

    ind_sim = _industry_overlap_canonical(candidate, assessment.industry)
    components.append(ind_sim * 0.30)
    total_weight += 0.30

    emp_sim = _employee_band_distance(emp_count, assessment_size)
    components.append(emp_sim * 0.30)
    total_weight += 0.30

    geo_sim = 0.5 if assessment.geography and geography and assessment.geography.lower() in [g.lower() for g in geography] else 0.0
    components.append(geo_sim * 0.15)
    total_weight += 0.15

    raw = (sum(components) / total_weight * 100) if total_weight > 0 else 0
    raw = max(0, min(100, raw))
    parts = []
    if emp_sim >= 0.5:
        parts.append("similar company size")
    if ind_sim >= 0.7:
        parts.append("matching industry")
    elif ind_sim >= 0.3:
        parts.append("related industry")
    if org_type:
        parts.append(f"{org_type} organization")
    reason = f"Supported by evidence from {' and '.join(parts)}" if parts else "Limited organizational context match"
    return ScoreComponent(score=round(raw, 1), weight=0.0, reason=reason)


def score_goal_alignment(candidate: dict, assessment: InvestigationRequest) -> ScoreComponent:
    metrics = candidate.get("metrics", [])
    raw, reason = _match_goal(assessment.desired_outcome, metrics)
    raw = raw * 100
    return ScoreComponent(score=round(raw, 1), weight=0.0, reason=reason)


def score_evidence_strength(candidate: dict) -> ScoreComponent:
    metrics = candidate.get("metrics", [])
    score = 50.0
    reasons = []

    has_quantified = any(m.get("percentage_change") is not None or m.get("absolute_change") is not None for m in metrics)
    if has_quantified:
        score += 15
        reasons.append("quantified outcomes")

    if candidate.get("independently_verified"):
        score += 10
        reasons.append("independently verified")

    has_baseline = candidate.get("has_baseline") or any(m.get("baseline_value") is not None for m in metrics)
    if has_baseline:
        score += 10
        reasons.append("baseline comparison available")

    n_metrics = len(metrics)
    if n_metrics >= 3:
        score += 10
    elif n_metrics >= 1:
        score += 5

    if candidate.get("vendor_reported"):
        score -= 15
        reasons.append("vendor-reported")

    if candidate.get("sample_size") and candidate["sample_size"] >= 30:
        score += 10
    elif candidate.get("sample_size") and candidate["sample_size"] >= 10:
        score += 5

    score = max(0, min(100, score))
    reason = f"Multiple independent quantitative sources" if reasons and "vendor" not in reasons else (
        "Quantified outcomes available" if has_quantified else
        "Limited quantified outcome data"
    )
    return ScoreComponent(score=round(score, 1), weight=0.0, reason=reason)


def score_implementation_fit(candidate: dict, assessment: InvestigationRequest) -> ScoreComponent:
    score = 50.0
    reasons = []

    cost = candidate.get("intervention_implementation_cost")
    if cost and assessment.budget_range:
        try:
            budget_num = float(assessment.budget_range.replace("$", "").replace(",", "").replace("K", "000").replace("M", "000000"))
            ratio = min(cost, budget_num) / max(cost, budget_num) if max(cost, budget_num) > 0 else 0
            if ratio >= 0.8:
                score += 15
                reasons.append("cost within typical budget range")
            elif ratio >= 0.5:
                score += 5
        except ValueError:
            pass

    has_software = bool(candidate.get("intervention_software"))
    has_teams = bool(candidate.get("intervention_teams_involved"))
    if has_software or has_teams:
        score += 10
        reasons.append("common business system integration")

    if candidate.get("intervention_pilot_used"):
        score += 10
        reasons.append("pilot-ready approach")

    duration = candidate.get("intervention_implementation_time_value")
    if duration and assessment.implementation_timeline:
        try:
            timeline_num = float(assessment.implementation_timeline.split()[0])
            if duration <= timeline_num:
                score += 10
                reasons.append("timeline compatible")
        except (ValueError, IndexError):
            pass

    if candidate.get("intervention_human_review_required") is False:
        score += 5
        reasons.append("fully automatable")

    score = max(0, min(100, score))
    reason = "; ".join(reasons) if reasons else "Moderate integration effort expected"
    return ScoreComponent(score=round(score, 1), weight=0.0, reason=reason)


def score_outcome_consistency(candidate: dict, all_candidates: List[dict]) -> ScoreComponent:
    families = candidate.get("intervention_families", [])
    same_family = [
        c for c in all_candidates
        if any(f in (c.get("intervention_families") or []) for f in families)
        and c.get("id") != candidate.get("id")
    ]
    if not same_family:
        return ScoreComponent(score=50.0, weight=0.0, reason="No comparable implementations to assess consistency")

    positive = sum(1 for c in same_family if c.get("result_status") in ("successful", "partial"))
    total = len(same_family)
    ratio = positive / total if total > 0 else 0

    if ratio >= 0.8:
        raw = 90
        reason = "Most comparable implementations reported positive outcomes"
    elif ratio >= 0.5:
        raw = 70
        reason = "Majority of comparable implementations reported positive outcomes"
    elif ratio >= 0.3:
        raw = 50
        reason = "Mixed outcomes in comparable implementations"
    else:
        raw = 30
        reason = "Most comparable implementations did not report positive outcomes"

    return ScoreComponent(score=raw, weight=0.0, reason=reason)


def compute_all_component_scores(
    candidate: dict,
    assessment: InvestigationRequest,
    all_candidates: List[dict],
) -> Dict[str, ScoreComponent]:
    return {
        "problem_alignment": score_problem_alignment(candidate, assessment),
        "organizational_similarity": score_organizational_similarity(candidate, assessment),
        "goal_alignment": score_goal_alignment(candidate, assessment),
        "evidence_strength": score_evidence_strength(candidate),
        "implementation_fit": score_implementation_fit(candidate, assessment),
        "outcome_consistency": score_outcome_consistency(candidate, all_candidates),
    }


def compute_match_score(components: Dict[str, ScoreComponent], weights: Dict[str, float]) -> float:
    total = 0.0
    for key, component in components.items():
        w = weights.get(key, 0.0)
        component.weight = w
        total += component.score * w
    return round(total, 1)
