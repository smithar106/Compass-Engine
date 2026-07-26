import re
import uuid
import math
import logging
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
    AlternativeComparison,
    SpecificIntervention,
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

METRIC_CATEGORIES: dict = {
    "cycle time": "time",
    "processing time": "time",
    "response time": "time",
    "ticket resolution time": "time",
    "plan development time": "time",
    "content generation time": "time",
    "promotional sla duration": "time",
    "error rate": "quality",
    "defect rate": "quality",
    "accuracy": "quality",
    "productivity": "efficiency",
    "throughput": "efficiency",
    "capacity": "efficiency",
    "utilization": "efficiency",
    "cost reduction": "cost",
    "annual cost savings": "cost",
    "revenue increase": "revenue",
    "year-over-year revenue growth": "revenue",
    "conversion rate": "revenue",
    "customer satisfaction": "satisfaction",
    "employee satisfaction": "satisfaction",
    "meeting time saved": "time",
    "monthly active users increase": "adoption",
    "compute capacity optimization": "infrastructure",
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


def _normalize_to_key(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _get_metric_category(metric_label: str) -> str:
    key = metric_label.lower()
    for pattern, cat in METRIC_CATEGORIES.items():
        if pattern in key or key in pattern:
            return cat
    return "other"


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
        for o in outcomes:
            if isinstance(o, str):
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
        intervention_cat = ex.get("intervention_category", "")
        status = ex.get("status", "")
        problem = ex.get("problem", "") or ""
        evidence_score = float(ex.get("evidence_score", 0))

        limitations = _build_comparable_limitations(ex)

        result.append(ComparableEvidence(
            record_id=rec_id,
            organization=ex.get("organization", "Unknown"),
            industry="",
            geography="",
            organization_size=ex.get("employee_count", 0),
            workflow=workflow_ctx,
            problem=problem,
            workflow_context=_describe_workflow_context(workflow_ctx),
            intervention=ex.get("intervention", ""),
            intervention_category=intervention_cat,
            intervention_description=intervention_desc,
            implementation_status=status,
            observed_outcome=outcome_display,
            outcome_summary=outcome_display,
            normalized_metrics=normalized,
            evidence_tier=tier,
            evidence_score=evidence_score,
            similarity_score=ex.get("similarity", 0),
            similarity_dimensions=ex.get("similarity_breakdown", {}),
            relevance_explanation=relevance,
            limitations=limitations,
            source_title=ex.get("organization", ""),
            source_url="",
            publication_date="",
        ))
    return result


def _build_comparable_limitations(ex: dict) -> str:
    limitations = []
    if ex.get("vendor_reported"):
        limitations.append("Vendor-reported outcome — may overstate results")
    if ex.get("status") in ("failed", "abandoned"):
        limitations.append("Implementation was unsuccessful or abandoned")
    metrics = ex.get("outcome_summaries", [])
    if not metrics or all(not m for m in metrics):
        limitations.append("Did not publish quantified outcome data")
    if not ex.get("cost_savings"):
        limitations.append("Did not publish implementation cost")
    return "; ".join(limitations[:3]) if limitations else ""


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
    return " \u2014 ".join(parts) if parts else "Comparable implementation"


def _pluralize(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word}s"


# ---------------------------------------------------------------------------
# Phase 2 — Strict financial-estimate policy
# ---------------------------------------------------------------------------
# Compass calculates organization-specific savings ONLY when the following
# inputs are present AND valid:
#   - annual workflow volume (or monthly x 12)
#   - current handling time per item
#   - loaded labor cost per hour
#   - evidence-supported improvement range from comparables
#
# None of these are collected by the current assessment. The function always
# returns insufficient_input and describes what is missing.
# ---------------------------------------------------------------------------

def _estimate_impact(
    comparables: list[ComparableEvidence],
    category_id: str,
    req: Optional[InvestigationRequest],
) -> tuple[ImpactEstimate, ImpactEstimate]:
    missing_savings = []
    missing_hours = []

    if not req or not req.people_involved:
        missing_hours.append("number of people involved")
    if not req or not req.workflow_frequency:
        missing_hours.append("workflow frequency or volume")

    missing_savings.extend(missing_hours)
    if not req or not req.budget_range:
        missing_savings.append("labor cost or budget data")
    missing_savings.append("annual workflow volume")
    missing_savings.append("current handling time")

    savings = ImpactEstimate(
        status="insufficient_input",
        missing_inputs=list(dict.fromkeys(missing_savings)),
        what_can_be_reported="Evidence-derived outcome ranges from comparable implementations are available instead.",
        prompt_for_user="Provide annual workflow volume, average handling time, and loaded labor cost for organization-specific savings estimates.",
        basis="Organization-specific financial estimates require annual workflow volume, current handling time, and loaded labor cost. None of these are collected in the current assessment.",
    )

    hours = ImpactEstimate(
        status="insufficient_input",
        missing_inputs=list(dict.fromkeys(missing_hours)),
        what_can_be_reported="Evidence-derived time-savings percentages from comparable implementations are available.",
        prompt_for_user="Provide annual workflow volume and average handling time for organization-specific hours estimates.",
        basis="Hours estimates require annual workflow volume and current handling time, which are not currently collected in the assessment.",
    )

    if comparables and any(c.normalized_metrics for c in comparables):
        savings.what_can_be_reported = "Evidence-derived outcome ranges from comparable implementations are available and shown below."
        hours.what_can_be_reported = "Evidence-derived outcome ranges from comparable implementations are available and shown below."

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
        basis="Default estimate \u2014 intervention category not recognized."
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
# Phase 3 — Evidence-derived outcome ranges with compatibility rules
# ---------------------------------------------------------------------------

METRIC_DIRECTION: dict = {
    "time": "reduction",
    "cost": "reduction",
    "error": "reduction",
    "defect": "reduction",
    "quality": "improvement",
    "efficiency": "improvement",
    "productivity": "improvement",
    "revenue": "improvement",
    "satisfaction": "improvement",
    "adoption": "improvement",
    "capacity": "improvement",
    "throughput": "improvement",
    "accuracy": "improvement",
}


def _metric_direction(metric_label: str, category: str) -> str:
    cat_dir = METRIC_DIRECTION.get(category, "improvement")
    return cat_dir


def _calculate_outcome_ranges(comparables: list[ComparableEvidence]) -> list[OutcomeRange]:
    from collections import defaultdict

    metric_groups = defaultdict(list)
    source_ids = defaultdict(set)

    for c in comparables:
        for m in c.normalized_metrics:
            raw_name = m.get("metric", "")
            val_str = m.get("value", "")
            key = _normalize_to_key(raw_name)
            if not key or not val_str:
                continue
            if _is_company_wide_metric(raw_name):
                continue

            try:
                if val_str.endswith("%"):
                    val = float(val_str.rstrip("%"))
                    unit = "%"
                elif val_str.startswith("$"):
                    val = float(val_str.replace("$", "").replace(",", ""))
                    unit = "currency"
                else:
                    val = float(val_str)
                    unit = "number"
            except ValueError:
                continue

            label = raw_name
            metric_groups[key].append({
                "label": label,
                "value": val,
                "unit": unit,
                "tier": c.evidence_tier,
                "source_id": c.record_id or c.organization,
            })
            source_ids[key].add(c.record_id or c.organization)

    ranges = []
    for key, values in sorted(metric_groups.items()):
        if len(values) < 1:
            continue

        label = values[0]["label"]
        unit = values[0]["unit"]

        same_unit = all(v["unit"] == unit for v in values)
        if not same_unit:
            ranges.append(OutcomeRange(
                metric_key=key,
                metric_label=label,
                metric_category=_get_metric_category(label),
                unit=unit,
                direction=_metric_direction(label, _get_metric_category(label)),
                sample_size=len(values),
                directly_comparable=False,
                compatibility_notes=f"Incompatible units within metrics — {_pluralize(len(values), 'value')} found but units vary",
                calculation_method="incompatible",
                source_record_ids=list(source_ids[key]),
            ))
            continue

        nums = [v["value"] for v in values]
        gold = sum(1 for v in values if v["tier"] == "gold")
        silver = sum(1 for v in values if v["tier"] == "silver")
        bronze = sum(1 for v in values if v["tier"] == "bronze")

        nums_sorted = sorted(nums)
        n = len(nums_sorted)

        if n >= 6:
            q1 = nums_sorted[n // 4]
            q3 = nums_sorted[3 * n // 4]
            iqr = q3 - q1
            lower_fence = q1 - 1.5 * iqr
            upper_fence = q3 + 1.5 * iqr
            filtered = [x for x in nums_sorted if lower_fence <= x <= upper_fence]
            calc_method = "median_iqr"
        elif n >= 3:
            filtered = nums_sorted
            calc_method = "median_minmax"
        else:
            calc_method = "single_value" if n == 1 else "median_minmax"
            filtered = nums_sorted

        if not filtered:
            filtered = nums_sorted

        f_sorted = sorted(filtered)
        mid = len(f_sorted) // 2
        if len(f_sorted) % 2:
            median = f_sorted[mid]
        else:
            median = (f_sorted[mid - 1] + f_sorted[mid]) / 2

        ranges.append(OutcomeRange(
            metric_key=key,
            metric_label=label,
            metric_category=_get_metric_category(label),
            unit=unit,
            direction=_metric_direction(label, _get_metric_category(label)),
            low=round(f_sorted[0], 1),
            median=round(median, 1),
            high=round(f_sorted[-1], 1),
            sample_size=len(values),
            gold_count=gold,
            silver_count=silver,
            bronze_count=bronze,
            directly_comparable=True,
            calculation_method=calc_method,
            source_record_ids=list(source_ids[key]),
        ))

    return ranges[:8]


# ---------------------------------------------------------------------------
# Phase 4 — Specific intervention generation
# ---------------------------------------------------------------------------

def _generate_specific_intervention(inv: dict, req: InvestigationRequest) -> SpecificIntervention:
    family_id = inv.get("family_id", "")
    problem = (req.problem_statement or "").strip()[:80]
    top_examples = inv.get("top_examples", [])

    title = _generate_specific_action(inv, req)
    description = inv.get("description", "")[:200]
    required_changes = _generate_required_changes(family_id)
    scope = _generate_scope_boundaries(family_id)
    prereqs = _generate_prerequisites(family_id, req)
    excluded = _generate_excluded_scope(family_id)

    return SpecificIntervention(
        title=title,
        description=description,
        required_changes=required_changes,
        scope_boundaries=scope,
        prerequisites=prereqs,
        excluded_scope=excluded,
    )


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
            return f"Standardize intake and automate {problem.lower()} with rule-based routing and exception handling"
        return "Standardize intake and automate approval routing with rule-based exception handling"
    elif family_id == "AI":
        if problem:
            return f"Add AI-assisted {problem.lower()} with human approval for final decisions"
        return "Add AI-assisted drafting and classification while retaining human approval for final decisions"
    elif family_id == "Software":
        if problem:
            return f"Implement a centralized platform for {problem.lower()} with SLA tracking and reporting"
        return "Implement a centralized workflow platform for ownership, routing, SLA tracking, and reporting"
    elif family_id == "Process_Redesign":
        target = problem if problem else "core operational workflows"
        return f"Redesign {target.lower()} to reduce handoffs, standardize inputs, and eliminate redundant steps"
    elif family_id == "Staffing":
        return "Restructure team allocation and add specialized roles to address capacity gaps"
    elif family_id == "Hybrid":
        return "Combine automation, AI, and process redesign for a comprehensive operational transformation"
    return inv.get("family_name", "Implement recommended solution")


def _generate_required_changes(family_id: str) -> list[str]:
    changes = {
        "Workflow_Automation": [
            "Document all process steps and decision points",
            "Define routing rules for each exception path",
            "Configure automation triggers and approval flows",
            "Establish monitoring and escalation procedures",
        ],
        "AI": [
            "Identify and prepare training data for the AI model",
            "Define confidence thresholds for automated decisions",
            "Set up human review queue for edge cases",
            "Establish model performance monitoring and retraining cadence",
        ],
        "Software": [
            "Select and configure the platform or suite",
            "Migrate data from existing systems",
            "Configure user roles, permissions, and workflows",
            "Integrate with existing systems via API or middleware",
        ],
        "Process_Redesign": [
            "Map current-state process with all stakeholders",
            "Design future-state process with elimination of waste",
            "Define new roles, responsibilities, and handoffs",
            "Implement process changes with training and communication",
        ],
        "Staffing": [
            "Define role requirements and skill gaps",
            "Recruit or reassign team members",
            "Establish training programs for new workflows",
            "Set up team performance metrics",
        ],
        "Hybrid": [
            "Assess which process steps benefit from automation vs human judgment",
            "Design the human-AI interaction model",
            "Implement automation layer with AI augmentation",
            "Establish governance model for decision rights",
        ],
    }
    return changes.get(family_id, ["Assess current process and define requirements"])


def _generate_scope_boundaries(family_id: str) -> list[str]:
    boundaries = {
        "Workflow_Automation": [
            "Limited to processes with clear rules and structured inputs",
            "Exceptions requiring judgment remain in human workflow",
            "Does not replace the system of record",
        ],
        "AI": [
            "AI assists but does not replace human decision-makers",
            "Limited to use cases with sufficient training data",
            "Model outputs require human validation for high-stakes decisions",
        ],
        "Software": [
            "Implementation scope limited to selected platform capabilities",
            "Custom development scoped to integration requirements",
            "Does not include business process redesign unless explicitly included",
        ],
        "Process_Redesign": [
            "Scope limited to documented current-state processes",
            "Changes affecting other departments require cross-functional agreement",
            "Technology changes scoped separately",
        ],
        "Staffing": [
            "Changes limited to the assessed department or workflow",
            "Does not include compensation or benefits changes",
            "Cross-functional moves require coordination with other departments",
        ],
        "Hybrid": [
            "Initial scope limited to highest-impact processes",
            "AI and automation components scoped separately",
            "Full transformation phased over multiple quarters",
        ],
    }
    return boundaries.get(family_id, ["Scope to be defined during implementation planning"])


def _generate_prerequisites(family_id: str, req: InvestigationRequest) -> list[str]:
    prereqs = []
    if not req.current_tools:
        prereqs.append("Inventory of current tools and systems")
    if not req.people_involved:
        prereqs.append("List of stakeholders and team members involved")
    if not req.budget_range:
        prereqs.append("Confirmed implementation budget")
    prereqs.append("Executive sponsor assigned")
    prereqs.append("Success criteria defined")
    return prereqs


def _generate_excluded_scope(family_id: str) -> list[str]:
    excluded = {
        "Workflow_Automation": [
            "Processes requiring human judgment or interpretation",
            "Systems with no API or integration capability",
            "Compliance-critical processes without legal review",
        ],
        "AI": [
            "Decisions with legal or compliance liability without human review",
            "Use cases with insufficient training data quality or volume",
            "Real-time safety-critical applications",
        ],
        "Software": [
            "Custom software development beyond integration work",
            "Replacement of core systems of record",
            "Process redesign not related to software implementation",
        ],
        "Process_Redesign": [
            "Technology selection or implementation",
            "Organizational restructuring beyond the assessed department",
            "Changes to compensation, benefits, or HR policies",
        ],
        "Staffing": [
            "Compensation structure changes",
            "Cross-departmental reorganizations",
            "Outsourcing arrangements without legal review",
        ],
        "Hybrid": [
            "Full organizational transformation in a single phase",
            "Unproven or experimental technologies",
            "Processes with undefined success criteria",
        ],
    }
    return excluded.get(family_id, ["Scope boundaries to be defined during planning"])


# ---------------------------------------------------------------------------
# Phase 5-6 — Ranking explanation with tradeoffs
# ---------------------------------------------------------------------------

def _build_ranking_explanation(ranked: list[Recommendation], interventions: list) -> Optional[WhyRankedFirst]:
    if not ranked:
        return None
    top = ranked[0]

    supporting_reasons = []
    if top.evidence_summary.total_comparables >= 3:
        supporting_reasons.append(
            f"{top.evidence_summary.total_comparables} comparable implementations reported measurable "
            f"{'outcomes' if top.evidence_summary.average_evidence_score > 50 else 'results'} in this area"
        )
    if top.evidence_summary.gold_count >= 1:
        supporting_reasons.append(f"{top.evidence_summary.gold_count} independently verified implementations with quantified outcomes")
    if top.confidence.score >= 0.5:
        supporting_reasons.append(
            f"Clear and repeatable {'routing rules' if 'Automation' in top.category else 'outcome patterns'} "
            f"were identified in comparable implementations"
        )
    if top.confidence.score >= 0.7:
        supporting_reasons.append("The intervention does not depend on training data or model governance")

    tradeoffs = []
    if top.evidence_summary.total_comparables < 5:
        tradeoffs.append("Limited comparable evidence — outcomes may vary in different organizational contexts")
    if "Automation" in top.category:
        tradeoffs.append("Complex exceptions may still require manual review")
        tradeoffs.append("Benefits depend on standardizing intake before automation")
    if top.category == "AI":
        tradeoffs.append("Model quality depends on training data availability and quality")
        tradeoffs.append("Requires ongoing monitoring and retuning")
    if top.category == "Software":
        tradeoffs.append("Integration with existing systems may take longer than expected")
        tradeoffs.append("User adoption and change management are critical success factors")
    if top.category == "Process_Redesign":
        tradeoffs.append("Requires strong stakeholder buy-in across teams")
        tradeoffs.append("Benefits may take longer to materialize than automation approaches")

    alternative_differences = []
    for i, r in enumerate(ranked[1:], 2):
        diff = _describe_alternative_difference(top, r, r.rank)
        if diff:
            alternative_differences.append(diff)

    summary = _generate_ranking_summary(top, ranked)

    return WhyRankedFirst(
        summary=summary,
        supporting_reasons=supporting_reasons[:4],
        tradeoffs=tradeoffs[:3],
        alternative_differences=alternative_differences,
    )


def _generate_ranking_summary(top: Recommendation, ranked: list) -> str:
    parts = []
    parts.append(
        f"{top.title} ranked first because comparable implementations showed stronger "
        f"{'cycle-time' if any('time' in r.metric_key for r in top.outcome_ranges) else 'operational'}"
        f" results"
    )
    if total := top.evidence_summary.total_comparables:
        parts.append(f"with {total} comparable implementations")
    if top.evidence_summary.gold_count:
        parts.append(f"including {top.evidence_summary.gold_count} independently verified cases")
    if ranked and len(ranked) > 1:
        alt_names = [r.title for r in ranked[1:3]]
        if alt_names:
            parts.append(f"versus the {alt_names[0].lower()}{' and ' + alt_names[1].lower() if len(alt_names) > 1 else ''} alternatives")
    return ". ".join(parts) + "."


def _describe_alternative_difference(top: Recommendation, alt: Recommendation, rank: int) -> dict:
    reasons = []
    if alt.evidence_summary.total_comparables < top.evidence_summary.total_comparables:
        reasons.append(f"Fewer comparable implementations ({alt.evidence_summary.total_comparables} vs {top.evidence_summary.total_comparables})")
    if alt.confidence.score < top.confidence.score:
        reasons.append(f"Lower evidence confidence ({alt.confidence.label})")
    if alt.evidence_summary.gold_count < top.evidence_summary.gold_count:
        reasons.append(f"Fewer independently verified sources")
    if alt.evidence_summary.average_evidence_score < top.evidence_summary.average_evidence_score:
        reasons.append("Less detailed outcome documentation")

    return {
        "alternative": alt.title,
        "rank": rank,
        "reasons": reasons[:3] if reasons else ["Less evidence depth overall"],
        "when_to_consider": (
            f"If {alt.title.lower()} aligns better with existing capabilities or resources"
            if rank == 2 else
            f"Worth exploring if top options prove impractical after initial validation"
        ),
    }


# ---------------------------------------------------------------------------
# Phase 7 — Alternative comparison
# ---------------------------------------------------------------------------

def _build_alternative_comparison(rec: Recommendation, rank: int) -> AlternativeComparison:
    return AlternativeComparison(
        category=rec.category,
        specific_intervention=rec.specific_action or rec.title,
        rank=rank,
        evidence_strength=_categorical_label(rec.confidence.score, "evidence"),
        outcome_support=_categorical_label(rec.evidence_summary.average_evidence_score / 100, "outcome"),
        data_requirements=_data_requirements_label(rec.category),
        implementation_complexity=_complexity_label(rec.category),
        expected_timeline=_timeline_label(rec.impact.implementation_timeline),
        team_requirements=_team_label(rec.impact.project_team),
        time_to_value=_ttv_label(rec.category),
        primary_advantages=_advantages(rec.category),
        primary_limitations=_limitations(rec.category),
        reason_for_rank=_rank_reason(rec, rank),
    )


def _categorical_label(score: float, context: str) -> str:
    if score >= 0.7:
        return "Strong"
    if score >= 0.4:
        return "Moderate"
    if score >= 0.2:
        return "Limited"
    return "Low"


def _data_requirements_label(category: str) -> str:
    labels = {
        "AI": "High — training data required",
        "Workflow_Automation": "Medium — process documentation required",
        "Software": "Medium — system access required",
        "Process_Redesign": "Low — stakeholder input required",
        "Staffing": "Low — role definition required",
        "Hybrid": "High — data and process documentation required",
    }
    return labels.get(category, "Medium")


def _complexity_label(category: str) -> str:
    labels = {
        "AI": "High",
        "Workflow_Automation": "Low to Medium",
        "Software": "Medium to High",
        "Process_Redesign": "Medium",
        "Staffing": "Low",
        "Hybrid": "High",
    }
    return labels.get(category, "Medium")


def _timeline_label(tl: TimelineEstimate) -> str:
    if tl.min_weeks and tl.max_weeks:
        return f"{tl.min_weeks:.0f}\u2013{tl.max_weeks:.0f} weeks"
    if tl.expected_weeks:
        return f"{tl.expected_weeks:.0f} weeks"
    return "To be determined"


def _team_label(team: ProjectTeam) -> str:
    if team.min_people and team.max_people:
        return f"{team.min_people}\u2013{team.max_people} people"
    return "To be determined"


def _ttv_label(category: str) -> str:
    labels = {
        "Workflow_Automation": "Quick (4\u20138 weeks)",
        "AI": "Medium (12\u201320 weeks)",
        "Software": "Medium (12\u201324 weeks)",
        "Process_Redesign": "Medium (8\u201316 weeks)",
        "Staffing": "Quick (4\u201312 weeks)",
        "Hybrid": "Longer (16\u201330 weeks)",
    }
    return labels.get(category, "Medium")


def _advantages(category: str) -> list[str]:
    adv = {
        "Workflow_Automation": ["Fast implementation", "Clear ROI from reduced manual effort", "Low technical risk"],
        "AI": ["Handles unstructured tasks", "Scales with volume", "Can improve over time"],
        "Software": ["Purpose-built functionality", "Vendor support and updates", "Standardized workflows"],
        "Process_Redesign": ["No new technology required", "Addresses root causes", "Builds organizational capability"],
        "Staffing": ["Directly addresses capacity", "Builds internal expertise", "Flexible and reversible"],
        "Hybrid": ["Comprehensive approach", "Balances automation and human judgment", "Higher potential impact"],
    }
    return adv.get(category, ["Effective approach for the assessed workflow"])


def _limitations(category: str) -> list[str]:
    lim = {
        "Workflow_Automation": ["Requires structured processes", "Exceptions need manual handling", "Limited to rule-based tasks"],
        "AI": ["Requires training data", "Needs ongoing monitoring", "Regulatory uncertainty"],
        "Software": ["Vendor lock-in risk", "Integration complexity", "Requires change management"],
        "Process_Redesign": ["Slower to implement", "Requires stakeholder buy-in", "Harder to measure ROI"],
        "Staffing": ["Hard to scale quickly", "Talent availability risk", "Higher ongoing cost"],
        "Hybrid": ["More complex to manage", "Requires cross-functional coordination", "Higher initial investment"],
    }
    return lim.get(category, ["Requires careful implementation planning"])


def _rank_reason(rec: Recommendation, rank: int) -> str:
    if rank == 1:
        return f"Highest confidence ({rec.confidence.label}), strongest evidence ({rec.evidence_summary.total_comparables} comparables)"
    if rec.evidence_summary.total_comparables < 3:
        return f"Limited comparable evidence ({rec.evidence_summary.total_comparables} implementations)"
    return f"Moderate evidence but lower confidence than top-ranked option"


# ---------------------------------------------------------------------------
# Phase 10 — Large outcome context
# ---------------------------------------------------------------------------

LARGE_OUTCOME_THRESHOLD_CURRENCY = 10_000_000


def _add_large_outcome_context(metric_label: str, value: float, unit: str) -> dict:
    if unit == "currency" and abs(value) >= LARGE_OUTCOME_THRESHOLD_CURRENCY:
        return {
            "scale": "enterprise-wide",
            "context": f"${value:,.0f} spans multiple initiatives and is not directly attributable to a single intervention",
            "attribution": "Limited — reported figure may include contributions from other concurrent changes",
            "used_in_estimate": False,
        }
    if unit == "%" and abs(value) > 100:
        return {
            "scale": "significant",
            "context": f"{value:.0f}% change is unusually large; verify attribution and baseline definition",
            "attribution": "Verify — large percentage changes may reflect small baselines",
            "used_in_estimate": False,
        }
    return {}


# ---------------------------------------------------------------------------
# Phase 11-12 — Assumptions, gaps, next validation step
# ---------------------------------------------------------------------------

def _build_assumptions_detail(inv: dict, comparables: list[ComparableEvidence], req: InvestigationRequest) -> list[Assumption]:
    assumptions = []
    total = len(comparables)

    if total < 5:
        assumptions.append(Assumption(
            title=f"Limited comparable evidence ({total} implementations)",
            explanation=f"Only {total} comparable implementations were available for this intervention type. Outcomes may vary significantly from observed ranges, especially in different organizational contexts or industries.",
            effect_on_recommendation="Observed outcome ranges may not fully represent expected results",
            effect_on_confidence="Confidence is reduced accordingly",
            resolution_action="Collect additional comparable implementations as they become available; run a pilot to validate",
        ))

    if not req.people_involved:
        assumptions.append(Assumption(
            title="Workforce size and involvement not provided",
            explanation="The number of people currently involved in the workflow was not provided. Evidence-derived ranges use data from comparable organizations, which may operate at a different scale.",
            effect_on_recommendation="Organization-specific scaling of outcomes may differ",
            effect_on_confidence="Cannot calculate per-person impact estimates",
            resolution_action="Provide the number of people involved in this workflow",
        ))

    if not req.workflow_frequency:
        assumptions.append(Assumption(
            title="Workflow volume not provided",
            explanation="How often the workflow runs was not provided. Without volume data, Compass cannot calculate organization-specific time or cost impact.",
            effect_on_recommendation="Impact shown as evidence-derived ranges rather than organization-specific estimates",
            effect_on_confidence="Moderate — ranges reflect comparable organizations, not your specific context",
            resolution_action="Provide annual or monthly workflow transaction volume",
        ))

    if not req.exception_rate:
        assumptions.append(Assumption(
            title="Exception rate not considered in estimates",
            explanation="Exception rate affects how much of the workflow can be automated or standardized. Higher exception rates reduce the applicable scope of most interventions.",
            effect_on_recommendation="Scope of automation may need adjustment based on actual exception patterns",
            effect_on_confidence="Not quantified — review exception handling during validation",
            resolution_action="Document current exception types and frequency",
        ))

    return assumptions


def _build_information_gaps(inv: dict, comparables: list, req: InvestigationRequest) -> list[InformationGap]:
    gaps = []

    gaps.append(InformationGap(
        title="Annual workflow volume and handling time",
        explanation="Current volume (transactions per period) and average handling time per item are not collected by the assessment. These are foundational inputs for calculating organization-specific labor savings.",
        effect_on_recommendation="Without these, Compass reports evidence-derived outcome ranges instead of organization-specific estimates",
        effect_on_confidence="Cannot calculate defensible savings — evidence ranges reflect comparable organizations",
        resolution_action="Add questions to the assessment for annual transaction volume and average handling time, or instruct the user to provide these during the next step",
    ))

    gaps.append(InformationGap(
        title="Loaded labor cost",
        explanation="The fully loaded hourly cost of employees involved in the workflow is not collected. This includes salary, benefits, overhead, and allocated costs.",
        effect_on_recommendation="Without labor cost, dollar-denominated savings cannot be calculated",
        effect_on_confidence="Reported savings from comparable organizations may not reflect your cost structure",
        resolution_action="Request average loaded cost per employee or use industry benchmarks with appropriate caveats",
    ))

    if total := len(comparables) < 3:
        gaps.append(InformationGap(
            title="More comparable implementations in your industry and company size",
            explanation=f"Only {total} comparable implementations were found. More data points would improve confidence that observed outcomes translate to your specific context.",
            effect_on_recommendation="Observed ranges may over- or under-state expected outcomes",
            effect_on_confidence="Limited — small sample size increases uncertainty",
            resolution_action="Expand evidence collection or validate through a pilot program",
        ))

    if not req.implementation_timeline:
        gaps.append(InformationGap(
            title="Preferred implementation timeline",
            explanation="The user's expected timeline was not provided. Timeline affects the phasing and scope of the recommended approach.",
            effect_on_recommendation="Timeline estimates use typical durations for the intervention type",
            effect_on_confidence="Estimated — actual duration depends on available resources and constraints",
            resolution_action="Collect expected implementation timeline or note as flexible",
        ))

    return gaps


def _build_next_validation_step(rank: int, category_id: str, comparables_total: int, req: InvestigationRequest) -> NextValidationStep:
    if rank == 1:
        if comparables_total < 5:
            action = "Measure a 4-week baseline for the current workflow"
            purpose = "Establish current cycle time, volume, exception rate, and manual effort before making implementation decisions"
            duration = "4 weeks"
            criteria = "At least 90% of workflow instances captured with complete timestamps"
            decision = "Produces the inputs required for a defensible savings estimate and pilot scope"
            inputs = ["Workflow transaction log or ticketing system data", "Timestamps for each process step", "Exception or rework tracking"]
            owner = "Workflow owner with operations analyst support"
        else:
            action = "Run a bounded pilot of the recommended approach in a single team or workflow"
            purpose = "Validate that the outcomes observed in comparable implementations translate to your specific organizational context"
            duration = "4\u20138 weeks for a well-scoped pilot with defined success metrics"
            criteria = "Measurable improvement in at least one of the outcome dimensions identified in this recommendation"
            decision = "Confirms whether to proceed with full-scale implementation"
            inputs = ["Selected pilot scope and team", "Baseline metrics before intervention", "Success criteria defined"]
            owner = "Process owner or project lead"
    else:
        action = "Evaluate this alternative alongside the primary recommendation"
        purpose = "Second- and third-ranked options may offer different risk profiles, cost structures, or organizational fit"
        duration = "1\u20132 weeks for feasibility assessment"
        criteria = "Clear understanding of relative benefits, costs, and risks vs the primary recommendation"
        decision = "Informs whether to pursue this alternative instead of or in parallel with the primary recommendation"
        inputs = ["Primary recommendation details", "Alternative-specific evidence review", "Stakeholder input on feasibility"]
        owner = "Project sponsor or evaluation team"

    return NextValidationStep(
        action=action,
        purpose=purpose,
        owner=owner,
        duration=duration,
        required_inputs=inputs,
        success_criteria=criteria,
        decision_enabled=decision,
    )


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


def _build_assumptions(inv: dict, total_comparables: int) -> list[str]:
    assumptions = []
    if total_comparables < 5:
        assumptions.append(f"Limited comparable implementations ({total_comparables}) \u2014 outcomes may vary significantly from estimates.")
    if inv.get("confidence", 0) < 50:
        assumptions.append("Moderate confidence \u2014 additional validation recommended before committing to implementation.")
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
        specific_intervention = _generate_specific_intervention(inv, req)

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
        next_step = _build_next_validation_step(rank, family_id, total, req)

        rec = Recommendation(
            rank=rank,
            is_compass_choice=rank == 1,
            intervention_id=family_id,
            category=family_id,
            title=inv.get("family_name", "Recommendation"),
            specific_action=specific_action,
            specific_intervention=specific_intervention,
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

    for i, rec in enumerate(ranked):
        rec.alternative_comparison = _build_alternative_comparison(rec, rec.rank)

    if ranked:
        ranked[0].why_ranked_first = _build_ranking_explanation(ranked, interventions)

    return ranked


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

    total_evidence = overall_conf.get("breakdown", {}).get("comparable_implementations", 0)
    method_summary = (
        f"Compass analyzed {total_evidence} comparable implementations across "
        f"{overall_conf.get('breakdown', {}).get('unique_organizations', 0)} organizations "
        f"to produce these recommendations. Each recommendation is ranked by evidence quality, "
        f"workflow fit, outcome consistency, and organizational similarity."
    )

    response = RecommendationResponse(
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
        methodology_summary=method_summary,
        assumptions=top_rec.assumptions_detail if top_rec else [],
        information_gaps=top_rec.information_gaps if top_rec else [],
        next_validation_steps=[top_rec.next_validation_step] if top_rec and top_rec.next_validation_step else [],
    )

    try:
        from compass_collector.api.storage import save_recommendation
        save_recommendation(response)
    except Exception:
        logger = logging.getLogger("compass-engine")
        logger.warning("Failed to persist recommendation result", exc_info=True)

    return response


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
