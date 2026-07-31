"""Evidence role classification.

Assigns each evidence record to one of five functional roles:
  - problem_fit: records from organizations facing the SAME problem
  - intervention: records supporting a specific solution path
  - implementation: records with rollout, partner, change-management detail
  - outcome: records with measured before/after results
  - risk: records with failures, limitations, or adverse findings

The recommendation assembler uses these roles to construct a balanced
evidence package rather than ranking by tier alone.
"""

from enum import Enum
from compass_collector.models.intervention import InterventionRecord


class EvidenceRole(str, Enum):
    PROBLEM_FIT = "problem_fit"
    INTERVENTION = "intervention"
    IMPLEMENTATION = "implementation"
    OUTCOME = "outcome"
    RISK = "risk"


def classify_evidence_roles(
    results: list[dict],
    query_problem: str = "",
    query_function: str = "",
) -> list[dict]:
    """Assign an evidence role to each result item.

    Returns the results list with an added 'evidence_role' field.
    """
    for item in results:
        roles = _assign_roles(item, query_problem, query_function)
        item["evidence_role"] = roles[0] if roles else EvidenceRole.PROBLEM_FIT
        item["evidence_roles"] = roles  # all applicable roles
    return results


def _assign_roles(item: dict, query_problem: str, query_function: str) -> list[EvidenceRole]:
    """Determine what evidence role(s) this record can serve."""
    roles = []
    rec = _get_record(item)

    problem = (item.get("problem", "") or "").lower()
    qp = query_problem.lower()
    problem_overlap = _word_overlap(problem, qp)

    intervention_families = item.get("intervention_families", [])
    status = item.get("status", "")

    # 1. Problem fit: orgs facing a similar problem
    if problem_overlap > 0.15 or (query_function and query_function in str(intervention_families)):
        roles.append(EvidenceRole.PROBLEM_FIT)

    # 2. Intervention: supports a specific solution path
    if intervention_families and len(intervention_families) > 0:
        roles.append(EvidenceRole.INTERVENTION)

    # 3. Implementation: has rollout/partner/change detail
    if rec and _has_implementation_detail(rec):
        roles.append(EvidenceRole.IMPLEMENTATION)
    elif item.get("lessons") and len(item.get("lessons", [])) > 0:
        roles.append(EvidenceRole.IMPLEMENTATION)

    # 4. Outcome: has measured results
    outcome_summaries = item.get("outcome_summaries", [])
    cost_savings = item.get("cost_savings")
    if outcome_summaries or (cost_savings is not None and cost_savings > 0):
        roles.append(EvidenceRole.OUTCOME)
    elif rec and (rec.has_baseline or rec.has_post_measurement):
        roles.append(EvidenceRole.OUTCOME)

    # 5. Risk: failures, limitations, negative findings
    negatives = item.get("negatives", [])
    if negatives or status in ("failed", "abandoned"):
        roles.append(EvidenceRole.RISK)

    # Default fallback
    if not roles:
        roles.append(EvidenceRole.PROBLEM_FIT)

    return roles


def _get_record(item: dict) -> InterventionRecord | None:
    try:
        from compass_collector.database import get_session
        rid = item.get("id")
        if not rid:
            return None
        s = get_session()
        try:
            return s.query(InterventionRecord).filter(InterventionRecord.id == rid).first()
        finally:
            s.close()
    except Exception:
        return None


def _has_implementation_detail(rec: InterventionRecord) -> bool:
    fields = ["implementation_partner", "implementation_pattern", "lessons_learned",
              "change_management", "rollout_strategy", "governance_model"]
    filled = 0
    for f in fields:
        val = getattr(rec, f, None)
        if val and (isinstance(val, list) and len(val) > 0) or (isinstance(val, str) and len(val.strip()) > 20):
            filled += 1
    return filled >= 2 or (rec.implementation_detail_score or 0) >= 7


def _word_overlap(a: str, b: str) -> float:
    """Simple word overlap ratio."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def assemble_evidence_package(
    results: list[dict],
    max_per_role: dict = None,
) -> dict:
    """Assemble a balanced evidence package by role.

    Args:
        results: classified result items (from classify_evidence_roles)
        max_per_role: max items per role (default: problem_fit=3, intervention=3,
                      implementation=3, outcome=3, risk=2)

    Returns:
        dict with role-grouped evidence and summary stats.
    """
    if max_per_role is None:
        max_per_role = {
            EvidenceRole.PROBLEM_FIT: 3,
            EvidenceRole.INTERVENTION: 3,
            EvidenceRole.IMPLEMENTATION: 3,
            EvidenceRole.OUTCOME: 3,
            EvidenceRole.RISK: 2,
        }

    packages = {role: [] for role in EvidenceRole}
    role_order = [
        EvidenceRole.OUTCOME,
        EvidenceRole.PROBLEM_FIT,
        EvidenceRole.INTERVENTION,
        EvidenceRole.IMPLEMENTATION,
        EvidenceRole.RISK,
    ]

    for role in role_order:
        limit = max_per_role.get(role, 3)
        for item in results:
            if role in item.get("evidence_roles", []):
                if len(packages[role]) < limit:
                    packages[role].append(item)

    # Compute tier summary
    tier_counts = {}
    for role, items in packages.items():
        count = {"gold": 0, "silver": 0, "bronze": 0}
        for item in items:
            rec = _get_record(item)
            tier = (rec.review_status if rec else "bronze") or "bronze"
            count[tier] = count.get(tier, 0) + 1
        tier_counts[role] = count

    # Implementation depth
    impl_depth = 0
    for item in packages.get(EvidenceRole.IMPLEMENTATION, []):
        rec = _get_record(item)
        if rec:
            if _has_implementation_detail(rec):
                impl_depth += 1

    outcome_count = len(packages.get(EvidenceRole.OUTCOME, []))
    risk_count = len(packages.get(EvidenceRole.RISK, []))

    return {
        "packages": {r.value: packages[r] for r in packages},
        "tier_breakdown": {r.value: tier_counts.get(r, {}) for r in packages},
        "implementation_depth": impl_depth,
        "outcome_evidence_count": outcome_count,
        "risk_evidence_count": risk_count,
        "is_balanced": (
            outcome_count >= 1
            and impl_depth >= 1
            and len(packages.get(EvidenceRole.INTERVENTION, [])) >= 1
        ),
    }


def build_traceability_map(evidence_package: dict) -> dict:
    """Build a map showing where each recommendation field comes from.

    For each output field in the recommendation response, maps it to
    one of: live_graph, computed_from_graph, or synthetic (labeled).
    """
    trace = {}
    packages = evidence_package.get("packages", {})

    def _count_source(role: str) -> int:
        return len(packages.get(role, []))

    trace["comparable_implementation_count"] = {
        "source": "live_graph",
        "value": sum(_count_source(r) for r in packages),
    }
    trace["evidence_tiers"] = {
        "source": "live_graph",
        "value": evidence_package.get("tier_breakdown", {}),
    }
    trace["confidence"] = {
        "source": "computed_from_graph",
        "inputs": ["outcome_count", "implementation_depth", "risk_count", "tier_breakdown"],
    }
    trace["expected_impact"] = {
        "source": "computed_from_graph",
        "inputs": ["outcome_summaries", "cost_savings", "percentage_change"],
    }
    trace["implementation_pattern"] = {
        "source": "live_graph" if evidence_package.get("implementation_depth", 0) > 0 else "synthetic",
        "warning": "insufficient implementation data in graph" if evidence_package.get("implementation_depth", 0) == 0 else None,
    }
    trace["partner_type"] = {
        "source": "live_graph" if _count_source("implementation") > 0 else "synthetic",
        "warning": "partner data derived from implementation records" if _count_source("implementation") > 0 else "no partner data available",
    }
    trace["blueprint_phases"] = {
        "source": "synthetic",
        "inputs": ["implementation_pattern", "rollout_strategy", "lessons_learned"],
    }
    trace["risks"] = {
        "source": "live_graph" if _count_source("risk") > 0 else "synthetic",
        "warning": "no risk evidence in graph" if _count_source("risk") == 0 else None,
    }

    return trace
