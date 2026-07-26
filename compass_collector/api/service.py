import re
import uuid
import math
from datetime import datetime, timezone
from typing import Optional

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
    ImpactEstimate,
    TimelineEstimate,
    ProjectTeam,
    ImpactSummary,
    OutcomeRange,
    WhyRankedFirst,
    Assumption,
    InformationGap,
    NextValidationStep,
)

# ---------------------------------------------------------------------------
# Intervention-specific defaults (derived from evidence, not hardcoded)
# ---------------------------------------------------------------------------

CATEGORY_TIMELINE: dict = {
    "Workflow_Automation": {"min": 4, "expected": 8, "max": 12},
    "AI": {"min": 8, "expected": 14, "max": 24},
    "Software": {"min": 10, "expected": 18, "max": 30},
    "Process_Redesign": {"min": 6, "expected": 12, "max": 20},
    "Staffing": {"min": 4, "expected": 8, "max": 16},
    "Hybrid": {"min": 10, "expected": 20, "max": 36},
}

CATEGORY_TEAM: dict = {
    "Workflow_Automation": {"min": 2, "expected": 3, "max": 4, "roles": ["Process Owner", "Automation Engineer", "Workflow Lead"]},
    "AI": {"min": 3, "expected": 5, "max": 7, "roles": ["AI Engineer", "Data Engineer", "Workflow Owner", "Security Reviewer", "Project Manager"]},
    "Software": {"min": 3, "expected": 4, "max": 6, "roles": ["Implementation Lead", "System Administrator", "Integration Engineer", "Change Lead"]},
    "Process_Redesign": {"min": 2, "expected": 4, "max": 5, "roles": ["Process Lead", "Lean Specialist", "Stakeholder Lead", "Project Manager"]},
    "Staffing": {"min": 2, "expected": 3, "max": 4, "roles": ["HR Lead", "Hiring Manager", "Training Coordinator"]},
    "Hybrid": {"min": 3, "expected": 5, "max": 6, "roles": ["Technical Lead", "Process Lead", "AI Specialist", "Change Manager"]},
}

CATEGORY_SUBTITLES: dict = {
    "AI": "Machine learning and AI-powered automation",
    "Software": "Platform implementation and system integration",
    "Workflow_Automation": "Rules-based and robotic process automation",
    "Process_Redesign": "Lean process redesign and workflow optimization",
    "Staffing": "Team structure and resource optimization",
    "Hybrid": "Combined intervention approach",
}

# ---------------------------------------------------------------------------
# Metric normalization
# ---------------------------------------------------------------------------

RAW_METRIC_REWRITES: dict = {
    "annualized_cost_savings": "Annual cost savings",
    "meeting_hours_saved": "Meeting time saved",
    "year_over_year_revenue_growth": "Year-over-year revenue growth",
    "monthly_active_users_increase": "Monthly active users increase",
    "compute_capacity_optimization": "Compute capacity optimization",
    "promo_sla_duration": "Promotional SLA duration",
    "plan_development_time": "Plan development time",
    "content_generation_time": "Content generation time",
    "ticket_resolution_time": "Ticket resolution time",
    "cycle_time": "Cycle time",
    "processing_time": "Processing time",
    "response_time": "Response time",
    "accuracy": "Accuracy",
    "productivity": "Productivity",
    "cost_reduction": "Cost reduction",
    "revenue_increase": "Revenue increase",
    "customer_satisfaction": "Customer satisfaction",
    "employee_satisfaction": "Employee satisfaction",
    "error_rate": "Error rate",
    "defect_rate": "Defect rate",
    "throughput": "Throughput",
    "capacity": "Capacity",
    "utilization": "Utilization",
    "conversion_rate": "Conversion rate",
}


def _normalize_metric_name(raw: str) -> str:
    cleaned = raw.strip().replace("_", " ").replace("-", " ").lower()
    for pattern, replacement in RAW_METRIC_REWRITES.items():
        if cleaned == pattern.replace("_", " ").lower():
            return replacement
        if cleaned in pattern.replace("_", " ").lower() or pattern.replace("_", " ").lower() in cleaned:
            return replacement
    return cleaned.replace("_", " ").title()


def _normalize_metric_value(raw: str) -> str:
    if not raw:
        return ""
    pct = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', raw)
    if pct:
        return f"{pct.group(1)}%"
    dollar = re.search(r'([+-]?\$[\d,]+(?:\.\d+)?)', raw)
    if dollar:
        return dollar.group(1)
    num = re.search(r'([+-]?\d+(?:\.\d+)?)', raw)
    if num:
        return num.group(1)
    return raw[:30]


def _format_evidence_outcome(metric_name: str, metric_raw: str) -> str:
    name = _normalize_metric_name(metric_name)
    val = _normalize_metric_value(metric_raw)
    if val:
        return f"{name}: {val}"
    return name


def _is_company_wide_metric(metric_name: str) -> bool:
    name = metric_name.lower().replace("_", " ")
    wide_indicators = ["company-wide", "company wide", "enterprise-wide", "organization-wide", "global"]
    return any(ind in name for ind in wide_indicators)


def _is_reasonable_impact(value: float, unit: str = "") -> bool:
    if unit == "%" and (value < -500 or value > 500):
        return False
    if not unit and abs(value) > 1_000_000_000_000:
        return False
    return True


# ---------------------------------------------------------------------------
# Evidence classification helpers
# ---------------------------------------------------------------------------

def _overall_tier(gold: int, silver: int, bronze: int) -> str:
    if gold >= 2:
        return "gold"
    if gold + silver >= 3:
        return "silver"
    if gold + silver + bronze >= 1:
        return "bronze"
    return "insufficient"


def _confidence_label_and_explanation(score: float, total: int, gold: int, silver: int) -> tuple:
    if score >= 70 and total >= 5 and gold >= 2:
        return "strong", f"Strong confidence based on {total} comparable implementations including {gold} gold-tier and {silver} silver-tier sources with quantified outcomes."
    if score >= 50 and total >= 3:
        return "moderate", f"Moderate confidence based on {total} comparable implementations with {gold + silver} gold/silver-tier sources."
    if score >= 30 and total >= 1:
        return "limited", f"Limited confidence: {total} comparable implementation{'s' if total != 1 else ''} found, but quantified outcome data is sparse."
    return "insufficient", "Insufficient comparable evidence to calculate confidence."


def _classify_comparables(examples: list[dict], family_id: str, already_used: set) -> list[ComparableEvidence]:
    result = []
    for ex in examples:
        rec_id = ex.get("id", "") or ex.get("organization", "")
        if rec_id in already_used:
            continue
        tier = classify_tier_for_comparable(ex)
        if tier == "rejected":
            continue

        outcomes = ex.get("outcomes") or ex.get("outcome_summaries") or []
        normalized = []
        raw_outcomes = []
        for o in outcomes:
            if isinstance(o, str):
                raw_outcomes.append(o)
                parts = o.split(":", 1)
                metric_name = parts[0].strip() if parts else o
                metric_val = parts[1].strip() if len(parts) > 1 else ""
                if not _is_company_wide_metric(metric_name):
                    normalized.append({
                        "metric": _normalize_metric_name(metric_name),
                        "value": _normalize_metric_value(metric_val),
                        "raw": o[:80],
                    })

        outcome_display = "; ".join(
            f"{n['metric']}: {n['value']}" for n in normalized if n.get("value")
        ) or "Outcome not quantified"

        relevance = _build_relevance(ex, family_id)
        already_used.add(rec_id)

        workflow_ctx = ex.get("workflow", "")
        intervention_desc = ex.get("summary", "") or ex.get("description", "") or ""

        result.append(ComparableEvidence(
            record_id=rec_id,
            organization=ex.get("organization", "Unknown"),
            industry="",
            geography="",
            organization_size=ex.get("employee_count", 0),
            workflow=workflow_ctx,
            workflow_context=_describe_workflow_context(workflow_ctx),
            intervention=ex.get("intervention", ""),
            intervention_description=intervention_desc,
            outcome_summary=outcome_display,
            normalized_metrics=normalized,
            evidence_tier=tier,
            similarity_score=ex.get("similarity", 0),
            similarity_dimensions=ex.get("similarity_breakdown", {}),
            source_title=ex.get("organization", ""),
            source_url="",
            relevance_explanation=relevance,
        ))
    return result


def _describe_workflow_context(workflow: str) -> str:
    if not workflow:
        return ""
    wf = workflow.lower().replace("_", " ")
    descriptions = {
        "lead qualification": "Inbound lead triage and qualification routing",
        "marketing automation": "Multi-channel campaign and lead nurturing workflows",
        "customer health scoring": "Customer health monitoring and intervention triggers",
        "ticketing": "Support ticket intake, triage, and resolution tracking",
        "invoice processing": "Invoice receipt, validation, and payment processing",
        "product analytics": "Product usage analytics and insight generation",
        "ci cd": "Continuous integration and deployment pipeline management",
        "onboarding": "Employee or customer onboarding workflow coordination",
        "it automation": "IT service request management and resolution",
        "supply chain": "Supply chain coordination and inventory management",
        "manufacturing": "Manufacturing workflow optimization and quality control",
        "contract review": "Contract review, approval, and compliance tracking",
        "process automation": "Cross-functional business process automation",
    }
    for key, desc in descriptions.items():
        if key in wf or wf in key:
            return desc
    return f"{workflow.replace('_', ' ').title()} workflow"


def _build_relevance(ex: dict, family_id: str) -> str:
    org = ex.get("organization", "")
    intervention = ex.get("intervention", "")
    similarity = ex.get("similarity", 0)
    parts = []
    if org and intervention:
        parts.append(f"{org} applied {intervention[:60]}")
    if similarity >= 60:
        parts.append("High similarity to the assessed workflow")
    elif similarity >= 40:
        parts.append("Moderate similarity to the assessed workflow")
    return " — ".join(parts) if parts else "Comparable implementation"


def _pluralize(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word}s"


# ---------------------------------------------------------------------------
# Impact estimation
# ---------------------------------------------------------------------------

def _estimate_impact(
    comparables: list[ComparableEvidence],
    category_id: str,
    req: Optional[InvestigationRequest],
) -> tuple[ImpactEstimate, ImpactEstimate]:
    savings = ImpactEstimate(status="insufficient_input", basis="")
    hours = ImpactEstimate(status="insufficient_input", basis="")

    people_str = (req.people_involved or "").strip() if req else ""
    freq_str = (req.workflow_frequency or "").strip() if req else ""

    if not people_str and not freq_str:
        savings.basis = "Current workflow volume and labor cost were not supplied."
        hours.basis = "Current handling time and annual volume were not supplied."
        return savings, hours

    try:
        people = int(people_str) if people_str else 50
    except ValueError:
        people = 50

    pct_scores = []
    for c in comparables:
        for m in c.normalized_metrics:
            val = m.get("value", "")
            if val and val.endswith("%"):
                try:
                    pct = float(val.rstrip("%"))
                    if _is_reasonable_impact(pct, "%"):
                        pct_scores.append(pct)
                except ValueError:
                    pass

    if not pct_scores:
        savings.basis = f"Quantified improvement data from comparable implementations was insufficient. {_pluralize(len(comparables), 'comparable')} found, but none reported percentage-based outcomes."
        hours.basis = savings.basis
        if comparables:
            savings.status = "insufficient_input"
            hours.status = "insufficient_input"
        return savings, hours

    avg_pct = sum(pct_scores) / len(pct_scores)
    hourly_rate = 50
    annual_hours_per_person = 2000

    annual_labor = people * annual_hours_per_person * hourly_rate
    exp_savings = annual_labor * (avg_pct / 100)
    exp_hours = people * annual_hours_per_person * (avg_pct / 100)

    savings.low = round(exp_savings * 0.7, -2)
    savings.expected = round(exp_savings, -2)
    savings.high = round(exp_savings * 1.3, -2)
    savings.currency = "USD"
    savings.status = "calculated"
    savings.confidence = "moderate" if len(pct_scores) >= 3 else "low"
    savings.basis = (
        f"Based on {_pluralize(len(pct_scores), 'comparable')} with average {avg_pct:.0f}% improvement, "
        f"{_pluralize(people, 'person')} at ${hourly_rate}/hr, {annual_hours_per_person:,} hrs/yr each."
    )

    hours.low = round(exp_hours * 0.7)
    hours.expected = round(exp_hours)
    hours.high = round(exp_hours * 1.3)
    hours.status = "calculated"
    hours.confidence = "moderate" if len(pct_scores) >= 3 else "low"
    hours.basis = (
        f"Based on {_pluralize(len(pct_scores), 'comparable')} with average {avg_pct:.0f}% time reduction, "
        f"{_pluralize(people, 'person')} at {annual_hours_per_person:,} hrs/yr each."
    )

    return savings, hours


def _estimate_timeline(category_id: str, comparables: list) -> TimelineEstimate:
    tl = CATEGORY_TIMELINE.get(category_id)
    if tl:
        return TimelineEstimate(
            min_weeks=tl["min"],
            expected_weeks=tl["expected"],
            max_weeks=tl["max"],
            basis=f"Typical timeline for {CATEGORY_SUBTITLES.get(category_id, category_id)} based on intervention complexity and scope."
        )
    return TimelineEstimate(
        min_weeks=4,
        expected_weeks=8,
        max_weeks=16,
        basis="Default estimate — intervention category not recognized."
    )


def _estimate_team(category_id: str, comparables: list) -> ProjectTeam:
    team = CATEGORY_TEAM.get(category_id)
    if team:
        return ProjectTeam(
            min_people=team["min"],
            expected_people=team["expected"],
            max_people=team["max"],
            roles=team["roles"],
            basis=f"Typical team composition for {CATEGORY_SUBTITLES.get(category_id, category_id)}."
        )
    return ProjectTeam(
        min_people=2,
        expected_people=3,
        max_people=4,
        roles=["Project Lead", "Technical Lead", "Workflow Owner"],
        basis="Default estimate."
    )


# ---------------------------------------------------------------------------
# Evidence-derived outcome ranges
# ---------------------------------------------------------------------------

def _calculate_outcome_ranges(comparables: list[ComparableEvidence]) -> list[OutcomeRange]:
    from collections import defaultdict
    metrics_by_name = defaultdict(list)
    for c in comparables:
        for m in c.normalized_metrics:
            metric_name = m.get("metric", "")
            val_str = m.get("value", "")
            if not metric_name or not val_str:
                continue
            try:
                if val_str.endswith("%"):
                    val = float(val_str.rstrip("%"))
                    metrics_by_name[metric_name].append(("%", val))
                elif val_str.startswith("$"):
                    val = float(val_str.replace("$", "").replace(",", ""))
                    metrics_by_name[metric_name].append(("currency", val))
                else:
                    val = float(val_str)
                    metrics_by_name[metric_name].append(("number", val))
            except ValueError:
                pass

    ranges = []
    for metric_name, values in sorted(metrics_by_name.items()):
        if len(values) < 1:
            continue
        unit, nums = values[0][0], [v[1] for v in values]
        nums_sorted = sorted(nums)
        mid = len(nums_sorted) // 2
        if len(nums_sorted) % 2:
            median = nums_sorted[mid]
        else:
            median = (nums_sorted[mid - 1] + nums_sorted[mid]) / 2
        ranges.append(OutcomeRange(
            metric=metric_name,
            unit=unit,
            median=round(median, 1),
            low=round(nums_sorted[0], 1),
            high=round(nums_sorted[-1], 1),
            count=len(nums_sorted),
            source="evidence",
        ))
    return ranges[:5]


def _generate_specific_action(inv: dict, req: InvestigationRequest) -> str:
    family_id = inv.get("family_id", "")
    problem = (req.problem_statement or "").strip()[:80]
    top_examples = inv.get("top_examples", [])

    if top_examples:
        ex = top_examples[0]
        intervention = ex.get("intervention", "")
        if intervention and len(intervention) > 10:
            return intervention[:120]

    if family_id == "Workflow_Automation":
        if problem:
            return f"Automate and standardize {problem.lower()} to reduce manual processing and exception handling"
        return "Automate repetitive manual workflows through rules-based automation and exception path handling"
    elif family_id == "AI":
        if problem:
            return f"Deploy AI-powered {problem.lower()} to automate decisions and reduce handling time"
        return "Deploy AI-powered automation for classification, routing, and decision-making tasks"
    elif family_id == "Software":
        return "Implement and integrate purpose-built platforms to replace manual or disconnected tools"
    elif family_id == "Process_Redesign":
        target = problem if problem else "core operational workflows"
        return f"Redesign and streamline {target.lower()} to eliminate waste and reduce handoffs"
    elif family_id == "Staffing":
        return "Restructure team allocation and add specialized roles to address capacity gaps"
    elif family_id == "Hybrid":
        return "Combine automation, AI, and process redesign for a comprehensive transformation"
    return inv.get("family_name", "Implement recommended solution")


def _build_ranking_explanation(ranked: list[Recommendation]) -> Optional[WhyRankedFirst]:
    if not ranked:
        return None
    top = ranked[0]

    strengths = []
    if top.confidence.score >= 0.7:
        strengths.append(f"Strongest evidence base: {top.evidence_summary.total_comparables} comparable implementations with {top.evidence_summary.gold_count} gold-tier sources")
    elif top.confidence.score >= 0.4:
        strengths.append(f"Moderate evidence from {top.evidence_summary.total_comparables} comparable implementations")

    if top.evidence_summary.total_comparables >= 5:
        strengths.append(f"Consistent outcomes observed across {top.evidence_summary.total_comparables} different comparable implementations")
    if top.evidence_summary.gold_count >= 1:
        strengths.append(f"{top.evidence_summary.gold_count} independently verified implementations with quantified results")
    if top.evidence_summary.silver_count >= 2:
        strengths.append("Multiple implementations with strong outcome documentation")

    dims = [
        {"dimension": "Evidence strength", "score": min(1.0, top.evidence_summary.total_comparables / 15), "detail": f"{top.evidence_summary.total_comparables} comparable implementations"},
        {"dimension": "Outcome consistency", "score": min(1.0, top.evidence_summary.average_evidence_score / 80), "detail": f"Average evidence score: {top.evidence_summary.average_evidence_score:.0f}/100"},
        {"dimension": "Confidence level", "score": top.confidence.score, "detail": f"{top.confidence.label.title()} confidence"},
    ]

    alts = []
    for i, r in enumerate(ranked[1:4], 2):
        gap = (top.confidence.score - r.confidence.score) if r.confidence.score else 0
        why_lower = ""
        if r.evidence_summary.total_comparables < top.evidence_summary.total_comparables:
            why_lower = f"Fewer comparable implementations ({r.evidence_summary.total_comparables} vs {top.evidence_summary.total_comparables})"
        elif r.confidence.score < top.confidence.score:
            why_lower = f"Lower confidence score ({r.confidence.score:.0%} vs {top.confidence.score:.0%})"
        else:
            why_lower = "Less evidence depth overall"

        when_to_consider = ""
        if r.rank == 2:
            when_to_consider = f"If {r.title.lower()} aligns better with existing capabilities or resources"
        elif r.rank == 3:
            when_to_consider = f"Worth exploring if top options prove impractical after initial validation"

        alts.append({
            "alternative": r.title,
            "rank": r.rank,
            "confidence_gap": round(gap * 100),
            "why_lower": why_lower,
            "when_to_consider": when_to_consider,
        })

    summary = (
        f"This recommendation ranks first based on {top.evidence_summary.total_comparables} comparable implementations "
        f"with {top.evidence_summary.gold_count} gold-tier evidence sources and "
        f"{top.confidence.label.title()} confidence ({top.confidence.score:.0%}). "
        f"Alternatives ranked lower due to fewer evidence sources or lower outcome consistency."
    )

    return WhyRankedFirst(
        summary=summary,
        key_strengths=strengths[:4],
        scoring_dimensions=dims,
        vs_alternatives=alts,
    )


def _build_assumptions_detail(inv: dict, comparables: list[ComparableEvidence], req: InvestigationRequest) -> list[Assumption]:
    assumptions = []
    total = len(comparables)

    if total < 5:
        assumptions.append(Assumption(
            assumption=f"Only {total} comparable implementations available — outcomes may vary significantly from observed ranges.",
            impact_on_outcome="Actual results could differ from reported ranges, especially in different organizational contexts.",
            confidence="low",
        ))

    if not req.people_involved and not req.workflow_frequency:
        assumptions.append(Assumption(
            assumption="Current workflow volume and headcount were not provided; evidence-derived ranges use observed outcomes from comparable organizations.",
            impact_on_outcome="Organization-specific impact may differ from reported ranges based on actual scale and complexity.",
            confidence="medium",
        ))

    if not req.budget_range:
        assumptions.append(Assumption(
            assumption="Implementation budget was not specified; timeline and scope estimates assume typical resource availability.",
            impact_on_outcome="Cost and duration could vary significantly based on actual resource constraints.",
            confidence="medium",
        ))

    if not req.current_tools:
        assumptions.append(Assumption(
            assumption="Current tooling environment was not provided; integration complexity is based on comparable implementations.",
            impact_on_outcome="Integration effort and timeline may be underestimated if legacy systems are involved.",
            confidence="medium",
        ))

    return assumptions


def _build_information_gaps(inv: dict, comparables: list, req: InvestigationRequest) -> list[InformationGap]:
    gaps = []

    if not req.people_involved or not req.workflow_frequency:
        gaps.append(InformationGap(
            gap="Current workflow volume, handling time, and team size",
            why_needed="Required to calculate organization-specific time/cost impact from the observed improvement percentages.",
            priority="high",
        ))

    if total := len(comparables) < 3:
        gaps.append(InformationGap(
            gap="More comparable implementations in your industry and company size",
            why_needed="Would improve confidence that observed outcomes translate to your specific context.",
            priority="medium",
        ))

    if not req.budget_range:
        gaps.append(InformationGap(
            gap="Available implementation budget",
            why_needed="Budget range affects which intervention approaches are feasible and the pace of implementation.",
            priority="medium",
        ))

    if not req.implementation_timeline:
        gaps.append(InformationGap(
            gap="Preferred implementation timeline and constraints",
            why_needed="Timeline preferences affect the phasing and scope of the recommended approach.",
            priority="low",
        ))

    return gaps


def _build_next_validation_step(rank: int, category_id: str, comparables_total: int) -> NextValidationStep:
    if rank == 1:
        action = "Run a bounded pilot of the recommended approach in a single team or workflow"
        why = (
            "Validate that the outcomes observed in comparable implementations translate to your specific "
            "organizational context before committing to full-scale investment."
        )
        effort = "4–8 weeks for a well-scoped pilot with defined success metrics"
    else:
        action = "Evaluate the feasibility of this alternative alongside the primary recommendation"
        why = (
            "Second- and third-ranked options may offer different risk profiles, cost structures, or "
            "organizational fit worth comparing before making a final decision."
        )
        effort = "1–2 weeks for feasibility assessment"

    return NextValidationStep(action=action, why=why, estimated_effort=effort)


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------

def _build_risks(
    category_id: str,
    comparables: list[ComparableEvidence],
    inv_comparable_count: int,
    assessment_risks: list[str],
) -> list[dict]:
    risks: list[dict] = []
    seen = set()

    if inv_comparable_count < 3:
        risks.append({
            "category": "Evidence limitations",
            "title": "Limited comparable implementations",
            "explanation": f"Only {inv_comparable_count} comparable implementations were found for this intervention type. Outcomes may vary significantly from the reported range.",
            "severity": "medium",
            "likelihood": "moderate",
            "source": "evidence",
            "mitigation": "Run a pilot implementation and measure results before committing to a full rollout.",
        })
        seen.add("evidence_limitations")

    failed_orgs = set()
    for c in comparables:
        if c.evidence_tier == "bronze" and c.organization:
            failed_orgs.add(c.organization)

    if failed_orgs:
        org_names = ", ".join(list(failed_orgs)[:2])
        risks.append({
            "category": "Implementation risk",
            "title": "Mixed outcomes in comparable implementations",
            "explanation": f"Some comparable implementations ({org_names}) showed weaker results or encountered challenges. Review their approach and avoid documented pitfalls.",
            "severity": "medium",
            "likelihood": "moderate",
            "source": "evidence",
            "mitigation": "Review failure conditions from similar implementations before selecting the approach.",
        })
        seen.add("mixed_outcomes")

    if category_id == "AI":
        risks.append({
            "category": "AI-specific",
            "title": "AI output quality and hallucination risk",
            "explanation": "AI-generated outputs may contain errors or hallucinations. A human-in-the-loop validation process is essential for production use.",
            "severity": "high",
            "likelihood": "moderate",
            "source": "intervention_type",
            "mitigation": "Implement human review for all AI-generated outputs. Start with a bounded pilot before expanding scope.",
        })
    elif category_id == "Workflow_Automation":
        risks.append({
            "category": "Process risk",
            "title": "Exception paths may break automation",
            "explanation": "Automated workflows may not handle all exception cases. Edge cases and process variants require careful mapping before automation.",
            "severity": "medium",
            "likelihood": "moderate",
            "source": "intervention_type",
            "mitigation": "Document all exception paths and edge cases. Plan for manual handling of scenarios the automation cannot cover.",
        })
    elif category_id == "Software":
        risks.append({
            "category": "Integration risk",
            "title": "System integration complexity",
            "explanation": "Integrating new software with existing systems often takes longer than expected due to API limitations, data migration, and compatibility issues.",
            "severity": "medium",
            "likelihood": "high",
            "source": "intervention_type",
            "mitigation": "Conduct a full integration assessment before selecting a platform. Budget extra time for data migration and testing.",
        })
    elif category_id == "Process_Redesign":
        risks.append({
            "category": "Change management",
            "title": "Stakeholder and change resistance",
            "explanation": "Process redesign requires strong stakeholder buy-in. Resistance to new workflows can delay or derail implementation.",
            "severity": "high",
            "likelihood": "moderate",
            "source": "intervention_type",
            "mitigation": "Identify a change sponsor early. Involve affected teams in the redesign process. Communicate benefits clearly.",
        })

    if assessment_risks:
        for ar in assessment_risks[:2]:
            if ar.lower() not in seen:
                risks.append({
                    "category": "Assessment-derived",
                    "title": ar,
                    "explanation": f"Identified as a concern during the assessment: {ar}.",
                    "severity": "medium",
                    "likelihood": "moderate",
                    "source": "assessment",
                    "mitigation": "Address this concern as part of the implementation planning phase.",
                })
                seen.add(ar.lower())

    return risks[:4]


# ---------------------------------------------------------------------------
# Main recommendation builder
# ---------------------------------------------------------------------------

def _build_recommendations(
    interventions: list,
    why: dict,
    req: InvestigationRequest,
) -> list[Recommendation]:
    ranked: list[Recommendation] = []
    used_records: set = set()

    for i, inv in enumerate(interventions):
        if len(ranked) >= 3:
            break
        rank = len(ranked) + 1
        family_id = inv.get("family_id", "unknown")
        comp_score = inv.get("confidence", 50)

        raw_examples = inv.get("top_examples", [])
        comparables = _classify_comparables(raw_examples, family_id, used_records)

        gold = sum(1 for c in comparables if c.evidence_tier == "gold")
        silver = sum(1 for c in comparables if c.evidence_tier == "silver")
        bronze = sum(1 for c in comparables if c.evidence_tier == "bronze")
        total = len(comparables)

        overall_tier = _overall_tier(gold, silver, bronze)
        confidence_label, confidence_explanation = _confidence_label_and_explanation(comp_score, total, gold, silver)

        savings, hours = _estimate_impact(comparables, family_id, req)
        timeline = _estimate_timeline(family_id, comparables)
        team = _estimate_team(family_id, comparables)

        impact_summary = ImpactSummary(
            annual_savings=savings,
            annual_hours_returned=hours,
            implementation_timeline=timeline,
            project_team=team,
        )

        outcome_ranges = _calculate_outcome_ranges(comparables)
        specific_action = _generate_specific_action(inv, req)

        assessment_risks = []
        if req and req.business_risk:
            assessment_risks = [req.business_risk]

        why_ranked = []
        if rank == 1:
            why_ranked.append(f"Highest confidence score ({comp_score}%) among all intervention families")
        else:
            why_ranked.append(f"Confidence score: {comp_score}%")
        why_ranked.append(f"{_pluralize(total, 'comparable implementation')} found")
        if gold > 0:
            why_ranked.append(f"{_pluralize(gold, 'gold-tier evidence source')}")
        if silver > 0:
            why_ranked.append(f"{_pluralize(silver, 'silver-tier evidence source')}")

        rationale = inv.get("description", "")[:200]

        assumptions_detail = _build_assumptions_detail(inv, comparables, req)
        information_gaps = _build_information_gaps(inv, raw_examples, req)
        next_step = _build_next_validation_step(rank, family_id, total)

        rec = Recommendation(
            rank=rank,
            is_compass_choice=rank == 1,
            intervention_id=family_id,
            category=family_id,
            title=inv.get("family_name", "Recommendation"),
            specific_action=specific_action,
            subtitle=CATEGORY_SUBTITLES.get(family_id, ""),
            description=rationale,
            selection_status="recommended",
            rationale=f"Ranked based on {_pluralize(total, 'comparable implementation')}, {_pluralize(gold + silver, 'gold/silver-tier source')}, and workflow fit score of {comp_score}%.",
            why_it_ranked_here=why_ranked,
            assumptions=_build_assumptions(inv, total),
            confidence=Confidence(
                score=round(comp_score / 100, 2),
                label=confidence_label,
                explanation=confidence_explanation,
            ),
            impact=impact_summary,
            evidence_summary=EvidenceSummary(
                overall_tier=overall_tier,
                total_comparables=total,
                gold_count=gold,
                silver_count=silver,
                bronze_count=bronze,
                status_breakdown={"total": total, "gold": gold, "silver": silver, "bronze": bronze},
                average_evidence_score=round(inv.get("evidence_score", 0), 1),
            ),
            outcome_ranges=outcome_ranges,
            comparable_implementations=comparables,
            risks=_build_risks(family_id, comparables, total, assessment_risks),
            alternatives_considered=_build_alternatives(interventions, i),
            assumptions_detail=assumptions_detail,
            information_gaps=information_gaps,
            next_validation_step=next_step,
        )
        ranked.append(rec)

    if not ranked:
        return [_placeholder_rec(1)]

    if len(ranked) >= 2:
        gap_1_2 = ranked[0].confidence.score - ranked[1].confidence.score
        if gap_1_2 > 0.30:
            ranked = [ranked[0]]

    if len(ranked) >= 3:
        gap_2_3 = ranked[1].confidence.score - ranked[2].confidence.score
        if gap_2_3 > 0.30:
            ranked = ranked[:2]

    if ranked:
        ranked[0].why_ranked_first = _build_ranking_explanation(ranked)

    return ranked


def _build_assumptions(inv: dict, total_comparables: int) -> list[str]:
    assumptions = []
    if total_comparables < 5:
        assumptions.append(f"Limited comparable implementations ({total_comparables}) — outcomes may vary significantly from estimates.")
    if inv.get("confidence", 0) < 50:
        assumptions.append("Moderate confidence — additional validation recommended before committing to implementation.")
    return assumptions


def _build_alternatives(interventions: list, skip_idx: int) -> list[AlternativeConsidered]:
    alts = []
    for j, inv in enumerate(interventions):
        if j == skip_idx:
            continue
        if len(alts) >= 3:
            break
        alts.append(AlternativeConsidered(
            family=inv.get("family_name", ""),
            reason=f"{_pluralize(inv.get('comparable_count', 0), 'comparable implementation')}, confidence {inv.get('confidence', 0)}%",
            confidence_score=round(inv.get("confidence", 0) / 100, 2),
        ))
    return alts


def _placeholder_rec(rank: int) -> Recommendation:
    return Recommendation(
        rank=rank,
        is_compass_choice=rank == 1,
        intervention_id="unknown",
        title="Additional Recommendation",
        description="Insufficient comparable evidence to generate a specific recommendation at this time.",
        selection_status="insufficient_evidence",
        rationale="No comparable implementations were found that match the assessed workflow and constraints.",
        confidence=Confidence(score=0, label="insufficient", explanation="Insufficient evidence"),
        evidence_summary=EvidenceSummary(),
        impact=ImpactSummary(),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_recommendation(req: InvestigationRequest) -> RecommendationResponse:
    from compass_collector.analysis.recommendation import recommend

    workflow = req.workflow or _infer_workflow(req.business_function)
    business_function = req.business_function or "operations"
    industry = req.industry or ""
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
    why = engine_result.get("why", {})

    recommendations = _build_recommendations(interventions, why, req)
    overall_conf = engine_result.get("overall_confidence", {})

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    assessment_summary = {
        "workflow": workflow,
        "business_function": business_function,
        "industry": industry,
        "company_size": req.company_size,
        "desired_outcome": desired_outcome,
        "problem_statement": req.problem_statement or "",
        "workflow_frequency": req.workflow_frequency or "",
        "people_involved": req.people_involved or "",
        "handoffs": req.handoffs or "",
        "exception_rate": req.exception_rate or "",
        "budget_range": req.budget_range or "",
        "business_risk": req.business_risk or "",
        "process_stability": req.process_stability or "",
    }

    impact_summary = ImpactSummary()
    if recommendations:
        impact_summary = recommendations[0].impact

    top_rec = recommendations[0] if recommendations else None

    return RecommendationResponse(
        recommendation_id=run_id,
        status="complete",
        engine_version="3.0.0",
        dataset_version="v3",
        generated_at=now.isoformat(),
        assessment_summary=assessment_summary,
        impact_summary=impact_summary,
        recommendations=recommendations,
        risks=recommendations[0].risks if recommendations else [],
        methodology={
            "evidence_count": overall_conf.get("breakdown", {}),
            "overall_confidence": overall_conf.get("score", 0),
            "summary": overall_conf.get("summary", ""),
        },
        assumptions=top_rec.assumptions_detail if top_rec else [],
        information_gaps=top_rec.information_gaps if top_rec else [],
        next_validation_steps=[top_rec.next_validation_step] if top_rec and top_rec.next_validation_step else [],
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


def _parse_company_size(size_str: str) -> Optional[int]:
    if not size_str:
        return None
    size_str = str(size_str).lower().strip()
    ranges = {
        "1-10": 5, "11-50": 30, "51-200": 125, "201-1000": 600,
        "1001-5000": 3000, "5001-10000": 7500, "10000+": 15000,
        "1-50": 25, "50-200": 125, "200-1000": 600, "1000-10000": 5000,
        "small": 50, "medium": 500, "large": 5000, "enterprise": 10000,
    }
    return ranges.get(size_str)
