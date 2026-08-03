"""Inspect step: per-category evidence-gap analysis.

Determines which decision categories have the largest evidence gaps *before*
any new source is sought. A category is (workflow, business_function). For each
we measure comparables volume, evidence tier depth, and Implementation
Intelligence field coverage (rollout strategy, validation gates/success
criteria, lessons, implementation pattern). Expected impact = demand × gap.

Pure and deterministic so the plan is testable and reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Evidence targets a category should meet to produce a defensible brief.
MIN_COMPARABLES = 5
MIN_GOLD = 1
MIN_SILVER = 3
FIELD_COVERAGE_TARGET = 0.5  # fraction of records that should carry each field

# Implementation Intelligence fields a brief needs; mapped to the source types
# that best fill them. Business evidence (vendor case studies, engineering
# blogs, consulting) is preferred over academic/arxiv so campaigns surface real
# implementations with measured ROI.
IMPLEMENTATION_FIELDS = {
    "rollout_strategy": ["vendor_case_study", "engineering_blog", "consulting"],
    "success_criteria": ["vendor_case_study", "government_audited", "financial_disclosure"],
    "lessons_learned": ["vendor_case_study", "engineering_blog", "consulting"],
    "implementation_pattern": ["vendor_case_study", "engineering_blog", "consulting"],
}

# Curated demand weights for common decision categories (0..1). Anything not
# listed gets a baseline demand; a real system would weight by Analyze queries.
DEFAULT_DEMAND: dict[str, float] = {
    "invoice_processing": 0.9, "onboarding": 0.8, "ticketing": 0.8,
    "lead_qualification": 0.75, "marketing_automation": 0.7, "ci_cd": 0.7,
    "contract_review": 0.65, "supply_chain": 0.7, "manufacturing": 0.6,
    "process_automation": 0.6,
}

# Keyword → demand for free-text workflow descriptions (the v3 subset stores
# verbose workflows like "Customer service call handling"), so business decision
# categories outrank incidental ones even without a canonical slug.
BUSINESS_CATEGORY_KEYWORDS: list[tuple[str, float]] = [
    ("invoice", 0.9), ("payment", 0.85), ("reconcil", 0.75), ("billing", 0.8),
    ("onboard", 0.8), ("ticket", 0.8), ("support", 0.75), ("service call", 0.75),
    ("lead", 0.75), ("qualif", 0.75), ("marketing", 0.7), ("campaign", 0.7),
    ("ci cd", 0.7), ("deploy", 0.7), ("contract", 0.65), ("rfp", 0.7),
    ("quoting", 0.7), ("supply chain", 0.7), ("inventory", 0.7), ("logistic", 0.7),
    ("manufactur", 0.6), ("financial close", 0.75), ("close", 0.7),
    ("procure", 0.7), ("vendor", 0.7), ("hr", 0.65), ("recruit", 0.65),
    ("workforce", 0.65), ("productivity", 0.6), ("document", 0.55),
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _workflow_slug(workflow: Any) -> str:
    return _SLUG_RE.sub("_", str(workflow or "").strip().lower()).strip("_")


def _keyword_demand(workflow: Any) -> float:
    """Map a free-text workflow description onto a business demand weight."""
    text = str(workflow or "").lower()
    best = 0.0
    for keyword, dem in BUSINESS_CATEGORY_KEYWORDS:
        if keyword in text:
            best = max(best, dem)
    return best


@dataclass
class GapCategory:
    workflow: str
    business_function: str
    total_records: int = 0
    gold: int = 0
    silver: int = 0
    bronze: int = 0
    field_coverage: dict[str, float] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    gap_score: float = 0.0
    demand: float = 0.0
    expected_impact: float = 0.0
    estimated_records_needed: int = 0
    proposed_source_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "business_function": self.business_function,
            "total_records": self.total_records,
            "gold": self.gold,
            "silver": self.silver,
            "bronze": self.bronze,
            "field_coverage": self.field_coverage,
            "missing_fields": self.missing_fields,
            "gap_score": round(self.gap_score, 3),
            "demand": round(self.demand, 3),
            "expected_impact": round(self.expected_impact, 3),
            "estimated_records_needed": self.estimated_records_needed,
            "proposed_source_types": self.proposed_source_types,
        }


def _record_workflow(rec: Any) -> str:
    comps = getattr(rec, "intervention_components", None) or {}
    if isinstance(comps, dict) and comps.get("workflow"):
        return str(comps["workflow"])
    return ""


def _record_function(rec: Any) -> str:
    bf = getattr(rec, "problem_business_function", None) or []
    if bf:
        return str(bf[0])
    return ""


def _record_tier(rec: Any) -> str:
    tier = str(getattr(rec, "evidence_level", "") or "").lower()
    if tier in ("gold", "silver", "bronze"):
        return tier
    return "bronze"


def _has_field(rec: Any, field: str) -> bool:
    value = getattr(rec, field, None)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _coverage(records: list, field: str) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if _has_field(r, field)) / len(records)


def _gap_score(total: int, gold: int, silver: int, coverage: dict) -> float:
    """Weighted deficit vs evidence targets, 0 (healthy) → 1 (critical)."""
    scores = []
    scores.append(min(1.0, (MIN_COMPARABLES - total) / MIN_COMPARABLES))
    scores.append(min(1.0, (MIN_GOLD - gold) / MIN_GOLD))
    scores.append(min(1.0, (MIN_SILVER - silver) / MIN_SILVER))
    for field, cov in coverage.items():
        scores.append(max(0.0, (FIELD_COVERAGE_TARGET - cov) / FIELD_COVERAGE_TARGET))
    return sum(scores) / len(scores)


def _missing_fields(coverage: dict) -> list[str]:
    return [f for f, cov in coverage.items() if cov < FIELD_COVERAGE_TARGET]


def _source_types_for(missing: list[str]) -> list[str]:
    types: list[str] = []
    for mf in missing:
        for st in IMPLEMENTATION_FIELDS.get(mf, []):
            if st not in types:
                types.append(st)
    return types


def analyze_gaps(records: list, demand: Optional[dict] = None) -> list[GapCategory]:
    """Rank decision categories by evidence gap × demand."""
    demand = demand or DEFAULT_DEMAND
    grouped: dict[tuple, list] = {}
    for rec in records:
        wf = _record_workflow(rec)
        bf = _record_function(rec)
        if not wf and not bf:
            continue
        key = (wf or "unknown_workflow", bf or "operations")
        grouped.setdefault(key, []).append(rec)

    categories = []
    for (workflow, bf), recs in grouped.items():
        gold = sum(1 for r in recs if _record_tier(r) == "gold")
        silver = sum(1 for r in recs if _record_tier(r) == "silver")
        coverage = {f: _coverage(recs, f) for f in IMPLEMENTATION_FIELDS}
        gap = _gap_score(len(recs), gold, silver, coverage)
        missing = _missing_fields(coverage)
        dem = max(_keyword_demand(workflow), demand.get(_workflow_slug(workflow), 0.4))
        need = max(0, MIN_COMPARABLES - len(recs)) + max(0, MIN_GOLD - gold)
        categories.append(
            GapCategory(
                workflow=workflow,
                business_function=bf,
                total_records=len(recs),
                gold=gold,
                silver=silver,
                bronze=len(recs) - gold - silver,
                field_coverage={k: round(v, 2) for k, v in coverage.items()},
                missing_fields=missing,
                gap_score=gap,
                demand=dem,
                expected_impact=gap * dem,
                estimated_records_needed=need,
                proposed_source_types=_source_types_for(missing),
            )
        )

    categories.sort(key=lambda c: -c.expected_impact)
    return categories
