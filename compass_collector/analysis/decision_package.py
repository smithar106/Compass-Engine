"""Decision Package v1 — the unified recommendation artifact.

Every recommendation returns a DecisionPackage containing:
  - problem_definition: what problem, who has it, how common
  - evidence_breakdown: by role (outcome, implementation, problem-fit, risk)
  - comparable_organizations: who solved it and how
  - implementation_patterns: rollout strategies, partners, governance
  - outcome_ranges: expected impact from comparable implementations
  - risk_profile: what could go wrong, failure modes
  - measurement_framework: what to track and how
  - learning_plan: what to measure, when to re-evaluate
  - defensibility_checklist: 8-question ✓/⚠/✗ assessment
  - defensibility_score: fraction of questions defensible from graph

This is the Decision Intelligence Engine output — one artifact,
not a scattered recommendation + evidence dump.
"""

from dataclasses import dataclass, field
from enum import Enum

from compass_collector.analysis.evidence_roles import EvidenceRole, assemble_evidence_package
from compass_collector.analysis.decision_defensibility import build_defensibility, AnswerSource


class ChecklistStatus(str, Enum):
    DEFENSIBLE = "defensible"         # ✓ answer exists from live graph
    PARTIAL = "partial"              # ⚠ answer exists but from computation or synthesis
    NOT_DEFENSIBLE = "not_defensible"  # ✗ no answer available
    UNKNOWN = "unknown"


@dataclass
class ChecklistItem:
    question: str
    short_answer: str
    status: ChecklistStatus
    source: AnswerSource
    evidence_count: int


@dataclass
class ProblemDefinition:
    statement: str
    business_function: str
    evidence_count: int
    industry_count: int
    industries: list[str]
    example_organizations: list[str]


@dataclass
class EvidenceBreakdown:
    total_records: int
    by_role: dict   # {role_name: count}
    by_tier: dict   # {gold, silver, bronze}
    organizations: list[str]
    industries: list[str]


@dataclass
class ImplementationProfile:
    patterns: list[str]
    partners: list[str]
    governance_models: list[str]
    executive_sponsors: list[str]
    rollout_strategies: list[str]
    pilot_structures: list[str]
    training_approaches: list[str]
    adoption_approaches: list[str]
    lessons_learned: list[str]
    richness_score: float  # 0-1, how much implementation detail exists


@dataclass
class OutcomeRange:
    metric: str
    min_change: float | None
    max_change: float | None
    median_change: float | None
    unit: str
    direction: str
    evidence_count: int


@dataclass
class RiskProfile:
    risk_signals: list[str]
    failure_count: int
    failure_organizations: list[str]
    lessons_from_failures: list[str]
    contradiction_flag: bool


@dataclass
class MeasurementFramework:
    recommended_metrics: list[str]
    baseline_capture: str
    evaluation_cadence: str
    source: str  # live_graph / synthetic


@dataclass
class DefensibilityChecklist:
    items: list[ChecklistItem]
    defensible_count: int
    partial_count: int
    not_defensible_count: int
    score: float  # fraction defensible (0-1)
    gaps: list[str]


@dataclass
class DecisionPackage:
    problem: ProblemDefinition
    evidence: EvidenceBreakdown
    implementation: ImplementationProfile
    outcomes: list[OutcomeRange]
    risks: RiskProfile
    measurement: MeasurementFramework
    defensibility: DefensibilityChecklist
    confidence_score: float
    confidence_label: str
    summary: str
    is_production_ready: bool


def build_decision_package(
    query_workflow: str,
    query_function: str,
    evidence_package: dict,
    confidence_score: float,
    confidence_label: str,
    all_items: list[dict] = None,
) -> DecisionPackage:
    """Build a complete DecisionPackage from evidence and confidence.

    This is the primary output of the Decision Intelligence Engine.
    """
    packages = evidence_package.get("packages", {})
    tier = evidence_package.get("tier_breakdown", {})

    if all_items is None:
        all_items = []
        for items in packages.values():
            all_items.extend(items)

    problem_items = packages.get("problem_fit", [])
    intervention_items = packages.get("intervention", [])
    impl_items = packages.get("implementation", [])
    outcome_items = packages.get("outcome", [])
    risk_items = packages.get("risk", [])

    # 1. Problem definition
    problem = _build_problem(query_workflow, query_function, problem_items, all_items)

    # 2. Evidence breakdown
    evidence = _build_evidence(all_items, tier)

    # 3. Implementation profile
    implementation = _build_implementation(impl_items, all_items)

    # 4. Outcome ranges
    outcomes = _build_outcomes(outcome_items)

    # 5. Risk profile
    risks = _build_risks(risk_items, all_items)

    # 6. Measurement framework
    measurement = _build_measurement(outcome_items)

    # 7. Defensibility checklist
    defense = build_defensibility(query_workflow, query_function, evidence_package, confidence_score, confidence_label)
    checklist = _build_checklist(defense)

    # 8. Production readiness
    is_production_ready = checklist.defensible_count >= 6 and confidence_score >= 45

    summary = (
        f"Decision Package: {problem.evidence_count} organizations across "
        f"{problem.industry_count} industries face this problem. "
        f"{len(intervention_items)} implementation patterns identified. "
        f"{len(outcome_items)} organizations with measured outcomes. "
        f"Defensibility: {checklist.defensible_count}/{len(checklist.items)} questions backed by live graph. "
        f"{'PRODUCTION READY' if is_production_ready else 'NEEDS MORE EVIDENCE — ' + str(len(checklist.gaps)) + ' gaps'}"
    )

    return DecisionPackage(
        problem=problem,
        evidence=evidence,
        implementation=implementation,
        outcomes=outcomes,
        risks=risks,
        measurement=measurement,
        defensibility=checklist,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        summary=summary,
        is_production_ready=is_production_ready,
    )


def _build_problem(query: str, function: str, problem_items: list, all_items: list) -> ProblemDefinition:
    orgs = list(set(i.get("organization", "") for i in all_items if i.get("organization")))[:10]
    industries_set = set()
    for i in all_items:
        ind = i.get("industry", [])
        if isinstance(ind, list):
            industries_set.update(ind)
    industries = sorted(industries_set)

    return ProblemDefinition(
        statement=query,
        business_function=function,
        evidence_count=len(all_items),
        industry_count=len(industries),
        industries=industries[:10],
        example_organizations=orgs[:5],
    )


def _build_evidence(all_items: list, tier: dict) -> EvidenceBreakdown:
    orgs = sorted(set(i.get("organization", "") for i in all_items if i.get("organization")))[:15]
    industries_set = set()
    for i in all_items:
        ind = i.get("industry", [])
        if isinstance(ind, list):
            industries_set.update(ind)

    gold = sum(tier.get(r, {}).get("gold", 0) for r in tier)
    silver = sum(tier.get(r, {}).get("silver", 0) for r in tier)
    bronze = sum(tier.get(r, {}).get("bronze", 0) for r in tier)

    role_counts = {}
    for i in all_items:
        role = i.get("evidence_role", EvidenceRole.PROBLEM_FIT)
        role_counts[role] = role_counts.get(role, 0) + 1

    return EvidenceBreakdown(
        total_records=len(all_items),
        by_role=role_counts,
        by_tier={"gold": gold, "silver": silver, "bronze": bronze},
        organizations=orgs,
        industries=sorted(industries_set)[:15],
    )


def _build_implementation(impl_items: list, all_items: list) -> ImplementationProfile:
    patterns = _collect_field(all_items, "implementation_pattern")
    partners = _collect_field(all_items, "implementation_partner")
    sponsors = [str(i.get("executive_sponsor", "")) for i in all_items if i.get("executive_sponsor")]
    rollouts = [i.get("rollout_strategy", "") for i in all_items if i.get("rollout_strategy")]
    pilots = [i.get("pilot_structure", "") for i in all_items if i.get("pilot_structure")]
    trainings = [i.get("training_approach", "") for i in all_items if i.get("training_approach")]
    adoptions = [i.get("adoption_approach", "") for i in all_items if i.get("adoption_approach")]
    lessons = _collect_field(all_items, "lessons_learned")

    filled_fields = len([x for x in [patterns, partners, sponsors, rollouts, pilots, trainings, adoptions, lessons] if x])
    richness = min(1.0, filled_fields / 6)

    return ImplementationProfile(
        patterns=list(set(patterns))[:10],
        partners=list(set(partners))[:10],
        governance_models=[i.get("governance_model", "") for i in all_items if i.get("governance_model")][:5],
        executive_sponsors=list(set(sponsors))[:5],
        rollout_strategies=rollouts[:3],
        pilot_structures=pilots[:3],
        training_approaches=trainings[:3],
        adoption_approaches=adoptions[:3],
        lessons_learned=list(set(lessons))[:10],
        richness_score=round(richness, 2),
    )


def _collect_field(items: list[dict], field: str) -> list:
    results = []
    for i in items:
        val = i.get(field, [])
        if isinstance(val, list):
            results.extend(val)
        elif isinstance(val, str) and val.strip():
            results.append(val)
    return results


def _build_outcomes(outcome_items: list) -> list[OutcomeRange]:
    ranges = []
    for i in outcome_items[:5]:
        summaries = i.get("outcome_summaries", [])
        if isinstance(summaries, list):
            for s in summaries:
                parts = s.split(":")
                metric = parts[0].strip() if parts else s
                ranges.append(OutcomeRange(
                    metric=metric[:60],
                    min_change=None,
                    max_change=None,
                    median_change=None,
                    unit="",
                    direction="improvement",
                    evidence_count=1,
                ))
    return ranges[:5]


def _build_risks(risk_items: list, all_items: list) -> RiskProfile:
    signals = []
    for i in risk_items:
        negatives = i.get("negatives", [])
        if isinstance(negatives, list):
            signals.extend(negatives)
        lessons = i.get("lessons", [])
        if isinstance(lessons, list):
            signals.extend(f"Lesson: {l}" for l in lessons)

    failed = [i.get("organization", "?") for i in all_items if i.get("status") in ("failed", "abandoned")]
    failure_lessons = _collect_field(risk_items, "lessons")

    return RiskProfile(
        risk_signals=list(set(signals))[:10],
        failure_count=len(failed),
        failure_organizations=failed[:5],
        lessons_from_failures=failure_lessons[:5],
        contradiction_flag=False,
    )


def _build_measurement(outcome_items: list) -> MeasurementFramework:
    metrics = set()
    for i in outcome_items:
        summaries = i.get("outcome_summaries", [])
        if isinstance(summaries, list):
            for s in summaries:
                metrics.add(s.split(":")[0].strip() if ":" in s else s[:50])

    if metrics:
        return MeasurementFramework(
            recommended_metrics=sorted(metrics)[:8],
            baseline_capture="Capture baseline metrics before implementation using operational systems",
            evaluation_cadence="Monthly for first quarter, quarterly thereafter",
            source="live_graph",
        )

    return MeasurementFramework(
        recommended_metrics=["Processing time", "Cost per unit", "Error rate", "Throughput", "User satisfaction"],
        baseline_capture="Establish baseline via operational data extraction before implementation",
        evaluation_cadence="Monthly for first 6 months, quarterly thereafter",
        source="synthetic",
    )


def _build_checklist(defense) -> DefensibilityChecklist:
    items = []
    for a in defense.answers:
        if a.source == AnswerSource.LIVE_GRAPH:
            status = ChecklistStatus.DEFENSIBLE
        elif a.source == AnswerSource.COMPUTED:
            status = ChecklistStatus.PARTIAL
        elif a.source == AnswerSource.SYNTHETIC:
            status = ChecklistStatus.PARTIAL
        else:
            status = ChecklistStatus.NOT_DEFENSIBLE

        items.append(ChecklistItem(
            question=a.question,
            short_answer=a.short_answer,
            status=status,
            source=a.source,
            evidence_count=a.evidence_count,
        ))

    defensible = sum(1 for i in items if i.status == ChecklistStatus.DEFENSIBLE)
    partial = sum(1 for i in items if i.status == ChecklistStatus.PARTIAL)
    not_defensible = sum(1 for i in items if i.status == ChecklistStatus.NOT_DEFENSIBLE)
    score = defensible / len(items) if items else 0

    return DefensibilityChecklist(
        items=items,
        defensible_count=defensible,
        partial_count=partial,
        not_defensible_count=not_defensible,
        score=round(score, 2),
        gaps=defense.gaps,
    )


def decision_package_to_dict(dp: DecisionPackage) -> dict:
    """Serialize DecisionPackage to API-safe dict."""
    return {
        "problem": {
            "statement": dp.problem.statement,
            "business_function": dp.problem.business_function,
            "evidence_count": dp.problem.evidence_count,
            "industry_count": dp.problem.industry_count,
            "industries": dp.problem.industries,
            "example_organizations": dp.problem.example_organizations,
        },
        "evidence": {
            "total_records": dp.evidence.total_records,
            "by_role": dp.evidence.by_role,
            "by_tier": dp.evidence.by_tier,
            "organizations": dp.evidence.organizations,
            "industries": dp.evidence.industries,
        },
        "implementation": {
            "patterns": dp.implementation.patterns,
            "partners": dp.implementation.partners,
            "governance_models": dp.implementation.governance_models,
            "executive_sponsors": dp.implementation.executive_sponsors,
            "rollout_strategies": dp.implementation.rollout_strategies,
            "pilot_structures": dp.implementation.pilot_structures,
            "training_approaches": dp.implementation.training_approaches,
            "adoption_approaches": dp.implementation.adoption_approaches,
            "lessons_learned": dp.implementation.lessons_learned,
            "richness_score": dp.implementation.richness_score,
        },
        "outcomes": [
            {
                "metric": o.metric,
                "min_change": o.min_change,
                "max_change": o.max_change,
                "median_change": o.median_change,
                "unit": o.unit,
                "direction": o.direction,
                "evidence_count": o.evidence_count,
            }
            for o in dp.outcomes
        ],
        "risks": {
            "risk_signals": dp.risks.risk_signals,
            "failure_count": dp.risks.failure_count,
            "failure_organizations": dp.risks.failure_organizations,
            "lessons_from_failures": dp.risks.lessons_from_failures,
        },
        "measurement": {
            "recommended_metrics": dp.measurement.recommended_metrics,
            "baseline_capture": dp.measurement.baseline_capture,
            "evaluation_cadence": dp.measurement.evaluation_cadence,
            "source": dp.measurement.source,
        },
        "defensibility": {
            "checklist": [
                {
                    "question": i.question,
                    "short_answer": i.short_answer,
                    "status": i.status.value,
                    "evidence_count": i.evidence_count,
                }
                for i in dp.defensibility.items
            ],
            "defensible_count": dp.defensibility.defensible_count,
            "partial_count": dp.defensibility.partial_count,
            "not_defensible_count": dp.defensibility.not_defensible_count,
            "score": dp.defensibility.score,
            "gaps": dp.defensibility.gaps,
        },
        "confidence_score": dp.confidence_score,
        "confidence_label": dp.confidence_label,
        "summary": dp.summary,
        "is_production_ready": dp.is_production_ready,
    }
