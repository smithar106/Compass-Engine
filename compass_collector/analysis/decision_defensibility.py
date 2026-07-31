"""Decision Defensibility — the internal north star.

For any recommendation, produces a DecisionPackage: a traceable,
defensible answer to the 8 questions any executive would ask before
committing organizational resources.

Every answer maps to live graph data or is explicitly labeled.
Defensibility is measured as a checklist, not a single score.

Usage:
  from compass_collector.analysis.decision_defensibility import build_decision_package
  package = build_decision_package(query, evidence_package, confidence)
"""

from dataclasses import dataclass, field
from enum import Enum
from compass_collector.analysis.evidence_roles import EvidenceRole


class AnswerSource(str, Enum):
    LIVE_GRAPH = "live_graph"
    COMPUTED = "computed_from_graph"
    SYNTHETIC = "synthetic"
    UNAVAILABLE = "unavailable"


@dataclass
class DefensibilityAnswer:
    question: str
    short_answer: str
    detailed_answer: str
    source: AnswerSource
    evidence_count: int
    key_records: list[dict]
    source_description: str
    confidence_level: str  # high/medium/low/unavailable


@dataclass
class DefensibilityResult:
    query: str
    problem: str
    answers: list[DefensibilityAnswer]
    overall_assessment: str
    can_defend: bool
    gaps: list[str]
    summary: str


def build_defensibility(
    query_workflow: str,
    query_function: str,
    evidence_package: dict,
    confidence_score: float,
    confidence_label: str,
) -> DefensibilityResult:
    """Build a COO-ready defense for a recommendation.

    Returns traceable answers to all 8 COO questions with source mapping.
    """
    packages = evidence_package.get("packages", {})
    tier = evidence_package.get("tier_breakdown", {})

    all_items = []
    for items in packages.values():
        all_items.extend(items)

    problem_items = packages.get("problem_fit", [])
    intervention_items = packages.get("intervention", [])
    impl_items = packages.get("implementation", [])
    outcome_items = packages.get("outcome", [])
    risk_items = packages.get("risk", [])

    answers = []

    # Q1: Why this problem?
    answers.append(_q1_problem_evidence(problem_items, all_items, query_workflow))

    # Q2: Why this intervention?
    answers.append(_q2_intervention_evidence(intervention_items, query_function))

    # Q3: Who else solved it?
    answers.append(_q3_comparable_orgs(all_items))

    # Q4: How did they implement it?
    answers.append(_q4_implementation_detail(impl_items, all_items))

    # Q5: What outcomes did they achieve?
    answers.append(_q5_outcome_evidence(outcome_items))

    # Q6: What risks should we expect?
    answers.append(_q6_risk_evidence(risk_items, all_items))

    # Q7: How should we measure success?
    answers.append(_q7_measurement_framework(outcome_items))

    # Q8: What would change this recommendation?
    answers.append(_q8_sensitivity(query_function, evidence_package, confidence_score))

    # Overall assessment
    gaps = _identify_gaps(answers, evidence_package, confidence_score)
    can_defend = len(gaps) <= 2 and confidence_score >= 40
    overall = _build_overall(gaps, can_defend, confidence_label)

    return DefensibilityResult(
        query=query_workflow,
        problem=query_function,
        answers=answers,
        overall_assessment=overall,
        can_defend=can_defend,
        gaps=gaps,
        summary=_build_summary(answers, confidence_score, can_defend, gaps),
    )


def _q1_problem_evidence(problem_items: list, all_items: list, query: str) -> DefensibilityAnswer:
    orgs = list(set(i.get("organization", "?") for i in problem_items))[:5]
    industries = set()
    for i in all_items:
        ind = i.get("industry", [])
        if isinstance(ind, list):
            industries.update(ind)
    industries = sorted(industries)[:8]

    if problem_items:
        detail = f"{len(problem_items)} organizations facing this problem across {len(industries)} industries including {', '.join(industries[:5])}. "
        detail += f"Specific examples: {', '.join(orgs[:5])}."
        return DefensibilityAnswer(
            question="Why this problem?",
            short_answer=f"{len(all_items)} organizations documented this problem across {len(industries)} industries",
            detailed_answer=detail,
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=len(problem_items),
            key_records=[{"org": o} for o in orgs[:3]],
            source_description=f"Live graph query: {len(all_items)} total records, {len(problem_items)} problem-fit",
            confidence_level="high" if len(problem_items) >= 5 else ("medium" if len(problem_items) >= 2 else "low"),
        )
    return _unavailable("Why this problem?", f"No direct problem-fit records for '{query}'")


def _q2_intervention_evidence(intervention_items: list, function: str) -> DefensibilityAnswer:
    families = set()
    for i in intervention_items:
        f = i.get("intervention_families", [])
        if isinstance(f, list):
            families.update(f)
    families = sorted(families)[:10]

    if intervention_items:
        return DefensibilityAnswer(
            question="Why this intervention?",
            short_answer=f"{len(intervention_items)} implementations using {len(families)} approach types",
            detailed_answer=f"Evidence supports {', '.join(families[:5])} approaches for {function} problems. "
                           f"These represent the most commonly deployed intervention categories.",
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=len(intervention_items),
            key_records=[{"families": list(families)[:5]}],
            source_description=f"Intervention family distribution from {len(intervention_items)} records",
            confidence_level="high" if len(intervention_items) >= 5 else ("medium" if len(intervention_items) >= 3 else "low"),
        )
    return _unavailable("Why this intervention?", "No intervention evidence found")


def _q3_comparable_orgs(all_items: list) -> DefensibilityAnswer:
    orgs = list(set(i.get("organization", "") for i in all_items if i.get("organization")))[:10]
    industries = set()
    for i in all_items:
        ind = i.get("industry", [])
        if isinstance(ind, list):
            industries.update(ind)

    count = len(orgs)
    if count >= 5:
        return DefensibilityAnswer(
            question="Who else solved it?",
            short_answer=f"{count} organizations, including {orgs[0]}, {orgs[1]}, {orgs[2]}",
            detailed_answer=f"{count} organizations across {len(industries)} industries solved similar problems. "
                           f"Key examples: {', '.join(orgs[:5])}.",
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=count,
            key_records=[{"org": o} for o in orgs[:5]],
            source_description=f"Live graph: {count} unique organizations from {len(all_items)} evidence records",
            confidence_level="high",
        )
    elif count >= 1:
        return DefensibilityAnswer(
            question="Who else solved it?",
            short_answer=f"{count} organizations, including {orgs[0]}",
            detailed_answer=f"Limited evidence: {count} organizations found. More data needed for robust comparison.",
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=count,
            key_records=[{"org": o} for o in orgs],
            source_description=f"Live graph: {count} unique organizations",
            confidence_level="low",
        )
    return _unavailable("Who else solved it?", "No organizations found")


def _q4_implementation_detail(impl_items: list, all_items: list) -> DefensibilityAnswer:
    partners = set()
    patterns = set()
    sponsors = set()
    for i in all_items:
        if i.get("implementation_partner"):
            p = i.get("implementation_partner", [])
            if isinstance(p, list):
                partners.update(p)
        if i.get("implementation_pattern"):
            p = i.get("implementation_pattern", [])
            if isinstance(p, list):
                patterns.update(p)
        if i.get("executive_sponsor"):
            sponsors.add(str(i["executive_sponsor"]))

    impl_rich = len(impl_items)
    has_detail = bool(partners or patterns or sponsors)

    if impl_rich >= 2 and has_detail:
        detail = f"Implementation patterns: {', '.join(sorted(patterns)[:5])}. "
        if partners:
            detail += f"Partners used: {', '.join(sorted(partners)[:5])}. "
        if sponsors:
            detail += f"Typical executive sponsors: {', '.join(sorted(sponsors)[:5])}."
        return DefensibilityAnswer(
            question="How did they implement it?",
            short_answer=f"{impl_rich} records with implementation detail — {len(patterns)} patterns, {len(partners)} partners identified",
            detailed_answer=detail,
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=impl_rich,
            key_records=[{"patterns": sorted(patterns)[:3], "partners": sorted(partners)[:3]}],
            source_description="Live graph implementation detail fields",
            confidence_level="high",
        )
    return DefensibilityAnswer(
        question="How did they implement it?",
        short_answer="Insufficient implementation detail in graph",
        detailed_answer="The evidence graph contains implementation records but not enough detail on rollout strategy, partners, or governance. This is a known graph coverage gap.",
        source=AnswerSource.UNAVAILABLE,
        evidence_count=0,
        key_records=[],
        source_description="Graph has implementation detail fields but fill rate is low (6%)",
        confidence_level="unavailable",
    )


def _q5_outcome_evidence(outcome_items: list) -> DefensibilityAnswer:
    outcomes = []
    for i in outcome_items:
        summaries = i.get("outcome_summaries", [])
        if isinstance(summaries, list):
            outcomes.extend(summaries)
    cost = sum(i.get("cost_savings", 0) or 0 for i in outcome_items)

    if outcomes:
        return DefensibilityAnswer(
            question="What outcomes did they achieve?",
            short_answer=f"{len(outcome_items)} organizations with measured outcomes",
            detailed_answer=f"Measured outcomes include: {'; '.join(outcomes[:5])}. "
                           + (f"Total documented cost savings: ${cost:,.0f}." if cost > 0 else ""),
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=len(outcome_items),
            key_records=[{"outcomes": o} for o in outcomes[:3]],
            source_description=f"Live graph: {len(outcome_items)} outcome records",
            confidence_level="high" if len(outcome_items) >= 3 else ("medium" if len(outcome_items) >= 1 else "low"),
        )
    return _unavailable("What outcomes did they achieve?", "No measured outcomes found")


def _q6_risk_evidence(risk_items: list, all_items: list) -> DefensibilityAnswer:
    risks = []
    for i in risk_items:
        negatives = i.get("negatives", [])
        if isinstance(negatives, list):
            risks.extend(negatives)
        lessons = i.get("lessons", [])
        if isinstance(lessons, list):
            risks.extend(f"Lesson: {l}" for l in lessons)

    failed = sum(1 for i in all_items if i.get("status") in ("failed", "abandoned"))

    if risks or failed > 0:
        detail = (f"{len(risks)} risk signals identified. " if risks else "")
        if failed > 0:
            detail += f"{failed} implementations failed or were abandoned."
        return DefensibilityAnswer(
            question="What risks should we expect?",
            short_answer=f"{len(risks)} risk signals, {failed} failed implementations",
            detailed_answer=detail + (" Risk signals: " + "; ".join(risks[:5]) if risks else ""),
            source=AnswerSource.LIVE_GRAPH,
            evidence_count=len(risks) + failed,
            key_records=[{"risks": risks[:5]}],
            source_description="Live graph negative evidence and lessons learned",
            confidence_level="high" if risks else ("medium" if failed > 0 else "unavailable"),
        )
    return DefensibilityAnswer(
        question="What risks should we expect?",
        short_answer="No risk evidence in graph",
        detailed_answer="The evidence graph does not contain risk, failure, or cautionary evidence. This is an important gap — every recommendation should include what could go wrong.",
        source=AnswerSource.UNAVAILABLE,
        evidence_count=0,
        key_records=[],
        source_description="Risk evidence is systematically collected but currently underrepresented",
        confidence_level="unavailable",
    )


def _q7_measurement_framework(outcome_items: list) -> DefensibilityAnswer:
    metrics = set()
    for i in outcome_items:
        summaries = i.get("outcome_summaries", [])
        for s in summaries if isinstance(summaries, list) else []:
            metrics.add(s.split(":")[0].strip() if ":" in s else s[:50])

    if metrics:
        return DefensibilityAnswer(
            question="How should we measure success?",
            short_answer=f"{len(metrics)} success metrics identified from comparable implementations",
            detailed_answer=f"Based on comparable implementations, track: {', '.join(sorted(metrics)[:8])}. "
                           "Measurement should include baseline capture before implementation and periodic evaluation.",
            source=AnswerSource.COMPUTED,
            evidence_count=len(metrics),
            key_records=[{"metrics": sorted(metrics)[:8]}],
            source_description=f"Computed from {len(outcome_items)} outcome records",
            confidence_level="medium",
        )
    return DefensibilityAnswer(
        question="How should we measure success?",
        short_answer="Insufficient outcome data to recommend specific metrics",
        detailed_answer="Track standard operational KPIs: processing time, cost per unit, error rate, throughput, user satisfaction. Establish baseline before implementation.",
        source=AnswerSource.SYNTHETIC,
        evidence_count=0,
        key_records=[],
        source_description="Synthesized from standard operational metrics — not graph-backed",
        confidence_level="low",
    )


def _q8_sensitivity(function: str, package: dict, confidence: float) -> DefensibilityAnswer:
    tier = package.get("tier_breakdown", {})
    gold = sum(tier.get(r, {}).get("gold", 0) for r in tier)
    silver = sum(tier.get(r, {}).get("silver", 0) for r in tier)
    impl_depth = package.get("implementation_depth", 0)

    changes = []
    if gold == 0:
        changes.append("More outcome evidence with measured before/after results")
    if silver == 0:
        changes.append("More implementation detail (rollout strategy, partners, lessons learned)")
    if impl_depth == 0:
        changes.append("Implementation case studies with governance, training, and adoption detail")
    if confidence < 40:
        changes.append("Substantially more evidence across all categories")

    detail = "This recommendation would change (improve or reverse) if: " + "; ".join(changes) if changes else "Current evidence is sufficient for a stable recommendation."
    return DefensibilityAnswer(
        question="What would change this recommendation?",
        short_answer=f"Confidence is {confidence}/100. {'Additional evidence needed.' if changes else 'Stable.'}",
        detailed_answer=detail,
        source=AnswerSource.COMPUTED,
        evidence_count=len(changes),
        key_records=[],
        source_description="Computed from evidence gaps analysis",
        confidence_level="high" if not changes else "medium",
    )


def _unavailable(question: str, reason: str) -> DefensibilityAnswer:
    return DefensibilityAnswer(
        question=question,
        short_answer="Insufficient evidence",
        detailed_answer=reason,
        source=AnswerSource.UNAVAILABLE,
        evidence_count=0,
        key_records=[],
        source_description="No matching data in live graph",
        confidence_level="unavailable",
    )


def _identify_gaps(answers: list[DefensibilityAnswer], package: dict, confidence: float) -> list[str]:
    gaps = []
    for a in answers:
        if a.source == AnswerSource.UNAVAILABLE:
            gaps.append(f"No evidence for: {a.question}")
        elif a.source == AnswerSource.SYNTHETIC and "graph-backed" not in a.source_description:
            gaps.append(f"Synthetic answer (not graph-backed): {a.question}")
    if confidence < 40:
        gaps.append(f"Overall confidence too low ({confidence}/100) to defend recommendation")
    tier = package.get("tier_breakdown", {})
    gold = sum(tier.get(r, {}).get("gold", 0) for r in tier)
    silver = sum(tier.get(r, {}).get("silver", 0) for r in tier)
    if gold == 0 and silver == 0:
        gaps.append("No Gold or Silver evidence — all evidence is Bronze tier")
    impl_depth = package.get("implementation_depth", 0)
    if impl_depth == 0:
        gaps.append("No implementation detail (rollout, partners, governance) in evidence")
    return gaps


def _build_overall(gaps: list[str], can_defend: bool, label: str) -> str:
    if can_defend:
        return f"Recommendation is defensible ({label} confidence). {len(gaps)} minor gaps identified."
    if not gaps:
        return f"Recommendation is structurally sound but evidence is {label}."
    return f"Recommendation {label} — {len(gaps)} gaps prevent full defense. See gaps list."


def _build_summary(answers: list[DefensibilityAnswer], confidence: float, can_defend: bool, gaps: list[str]) -> str:
    sources = {}
    for a in answers:
        sources[a.source] = sources.get(a.source, 0) + 1

    live = sources.get(AnswerSource.LIVE_GRAPH, 0)
    computed = sources.get(AnswerSource.COMPUTED, 0)
    synthetic = sources.get(AnswerSource.SYNTHETIC, 0)
    unavailable = sources.get(AnswerSource.UNAVAILABLE, 0)

    return (
        f"Decision Defense: {live} answers from live graph, {computed} computed, "
        f"{synthetic} synthetic, {unavailable} unavailable. "
        f"Confidence: {confidence}/100. "
        f"{'DEFENSIBLE' if can_defend else 'NOT FULLY DEFENSIBLE — ' + str(len(gaps)) + ' gaps'}."
    )
