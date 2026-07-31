"""Implementation Defensibility Coverage — measures extraction completeness.

Tracks which implementation fields are populated across evidence records
and whether a query's evidence package has sufficient density to support
a defensible recommendation.

This metric replaces "total Silver count" as the primary quality indicator.

A recommendation is production-ready only when its evidence package passes:
  - defensibility >= 6/8
  - confidence >= 45
  - implementation_answer = defensible
  - all material claims have resolvable provenance
"""

from dataclasses import dataclass, field
from collections import Counter


IMPLEMENTATION_FIELDS = {
    "implementation_pattern": "rollout sequence (pilot → department → enterprise)",
    "implementation_partner": "who delivered the implementation",
    "executive_sponsor": "who owned implementation at exec level",
    "pilot_structure": "was there a pilot, scope and duration",
    "rollout_strategy": "step-by-step rollout description",
    "governance_model": "governance structure (steering committee, PMO, etc.)",
    "training_approach": "how users were trained",
    "adoption_approach": "how adoption was driven",
    "change_management": "change-management approach",
    "lessons_learned": "what failed or had to be adjusted",
    "implementation_team_structure": "internal vs contractor mix, cross-functional structure",
    "budget_range": "approximate budget",
    "key_decision_makers": "roles of key decision makers",
    "success_criteria": "what defined success / validation gates",
    "intervention_implementation_time_value": "how long rollout took",
    "implementation_detail_score": "detail score from extraction",
}


@dataclass
class ImplementationCoverage:
    """Coverage metric for a set of evidence records."""
    total_records: int
    records_with_implementation: int
    field_counts: dict  # {field_name: count}
    field_rates: dict   # {field_name: rate}
    has_pattern: bool
    has_partner: bool
    has_rollout: bool
    has_lessons: bool
    has_change_mgmt: bool
    has_validation: bool  # success_criteria or pilot_structure
    has_governance: bool
    has_sponsor: bool
    has_training: bool
    has_adoption: bool
    richness_score: float  # 0-1, fraction of fields with at least 1 populated record
    enough_for_production: bool


def compute_implementation_coverage(records: list) -> ImplementationCoverage:
    """Measure how much implementation detail exists across evidence records.

    records can be dicts (from retrieval) or InterventionRecord objects.
    """
    total = len(records)
    if total == 0:
        return _empty_coverage()

    field_counts = Counter()
    records_with_impl = 0

    for rec in records:
        has_any = False
        for field in IMPLEMENTATION_FIELDS:
            val = _get_field(rec, field)
            if _is_populated(val):
                field_counts[field] += 1
                has_any = True
        if has_any:
            records_with_impl += 1

    field_rates = {
        f: round(field_counts.get(f, 0) / total, 2) if total > 0 else 0
        for f in IMPLEMENTATION_FIELDS
    }

    # Boolean coverage flags
    has_pattern = field_counts.get("implementation_pattern", 0) > 0
    has_partner = field_counts.get("implementation_partner", 0) > 0 or field_counts.get("implementation_team_structure", 0) > 0
    has_rollout = field_counts.get("rollout_strategy", 0) > 0 or field_counts.get("implementation_pattern", 0) > 0
    has_lessons = field_counts.get("lessons_learned", 0) > 0
    has_change_mgmt = field_counts.get("change_management", 0) > 0 or field_counts.get("training_approach", 0) > 0
    has_validation = field_counts.get("success_criteria", 0) > 0 or field_counts.get("pilot_structure", 0) > 0
    has_governance = field_counts.get("governance_model", 0) > 0
    has_sponsor = field_counts.get("executive_sponsor", 0) > 0 or field_counts.get("key_decision_makers", 0) > 0
    has_training = field_counts.get("training_approach", 0) > 0
    has_adoption = field_counts.get("adoption_approach", 0) > 0

    # Richness: fraction of fields that have at least 1 populated record
    populated_fields = sum(1 for f in IMPLEMENTATION_FIELDS if field_counts.get(f, 0) > 0)
    richness = populated_fields / len(IMPLEMENTATION_FIELDS) if IMPLEMENTATION_FIELDS else 0

    # Production threshold: need at least 3 key fields populated
    key_flags = [has_pattern, has_rollout, has_lessons, has_change_mgmt or has_governance, has_partner or has_sponsor]
    enough_for_production = sum(key_flags) >= 3 and records_with_impl >= 2 and richness >= 0.15

    return ImplementationCoverage(
        total_records=total,
        records_with_implementation=records_with_impl,
        field_counts=dict(field_counts),
        field_rates=field_rates,
        has_pattern=has_pattern,
        has_partner=has_partner,
        has_rollout=has_rollout,
        has_lessons=has_lessons,
        has_change_mgmt=has_change_mgmt,
        has_validation=has_validation,
        has_governance=has_governance,
        has_sponsor=has_sponsor,
        has_training=has_training,
        has_adoption=has_adoption,
        richness_score=round(richness, 2),
        enough_for_production=enough_for_production,
    )


def _get_field(rec, field: str):
    """Get a field from either a dict or an object."""
    if isinstance(rec, dict):
        return rec.get(field)
    return getattr(rec, field, None)


def _is_populated(val) -> bool:
    """Check if a field value contains meaningful data."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val > 0
    if isinstance(val, list):
        return len(val) > 0 and any(v for v in val)
    if isinstance(val, str):
        return len(val.strip()) > 10
    if isinstance(val, dict):
        return len(val) > 0
    return False


def _empty_coverage() -> ImplementationCoverage:
    return ImplementationCoverage(
        total_records=0,
        records_with_implementation=0,
        field_counts={},
        field_rates={},
        has_pattern=False,
        has_partner=False,
        has_rollout=False,
        has_lessons=False,
        has_change_mgmt=False,
        has_validation=False,
        has_governance=False,
        has_sponsor=False,
        has_training=False,
        has_adoption=False,
        richness_score=0.0,
        enough_for_production=False,
    )


def coverage_checklist(coverage: ImplementationCoverage) -> list[dict]:
    """Produce a checklist of implementation coverage status."""
    return [
        {"field": "implementation_pattern", "label": "Sequence of steps (pilot → department → enterprise)", "covered": coverage.has_pattern, "count": coverage.field_counts.get("implementation_pattern", 0)},
        {"field": "implementation_partner", "label": "Who owned or delivered the implementation", "covered": coverage.has_partner, "count": coverage.field_counts.get("implementation_partner", 0)},
        {"field": "rollout_strategy", "label": "How rollout was sequenced", "covered": coverage.has_rollout, "count": coverage.field_counts.get("rollout_strategy", 0)},
        {"field": "lessons_learned", "label": "What failed or had to be adjusted", "covered": coverage.has_lessons, "count": coverage.field_counts.get("lessons_learned", 0)},
        {"field": "change_management", "label": "Change-management actions required", "covered": coverage.has_change_mgmt, "count": coverage.field_counts.get("change_management", 0)},
        {"field": "success_criteria", "label": "Validation gate before scaling", "covered": coverage.has_validation, "count": coverage.field_counts.get("success_criteria", 0)},
        {"field": "governance_model", "label": "Governance model used", "covered": coverage.has_governance, "count": coverage.field_counts.get("governance_model", 0)},
        {"field": "executive_sponsor", "label": "Executive owner", "covered": coverage.has_sponsor, "count": coverage.field_counts.get("executive_sponsor", 0)},
        {"field": "training_approach", "label": "How users were trained", "covered": coverage.has_training, "count": coverage.field_counts.get("training_approach", 0)},
        {"field": "adoption_approach", "label": "How adoption was driven", "covered": coverage.has_adoption, "count": coverage.field_counts.get("adoption_approach", 0)},
    ]
