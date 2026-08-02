"""Validation of LLM-enriched records.

Checks the extracted payload for schema conformance, value sanity, and
cross-field consistency. Produces a ``ValidationReport`` with per-rule results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

ALLOWED_INTERVENTION_CATEGORIES = {
    "Workflow_Automation", "AI", "Software", "Process_Redesign", "Staffing", "Hybrid",
}

ALLOWED_EVIDENCE_TIERS = {"gold", "silver", "bronze", "rejected"}

REQUIRED_TEXT_FIELDS = [
    "organization_name",
    "workflow",
    "intervention_title",
]

NON_EMPTY_WORDS = 1  # a text field with fewer words is treated as missing


def _has_content(value: Any, min_words: int = NON_EMPTY_WORDS) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(_has_content(v, 1) for v in value)
    if isinstance(value, dict):
        return bool(value)
    return len(str(value).split()) >= min_words


@dataclass
class ValidationReport:
    valid: bool
    issues: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "issues": self.issues,
            "checks": self.checks,
        }


Rule = Callable[[dict], list[str]]


def _rule_required_fields(payload: dict) -> list[str]:
    issues = []
    for f in REQUIRED_TEXT_FIELDS:
        if not _has_content(payload.get(f)):
            issues.append(f"missing required field: {f}")
    return issues


def _rule_intervention_category(payload: dict) -> list[str]:
    cat = payload.get("intervention_category") or ""
    if cat and cat not in ALLOWED_INTERVENTION_CATEGORIES:
        return [f"invalid intervention_category: {cat!r}"]
    return []


def _rule_evidence_tier(payload: dict) -> list[str]:
    tier = str(payload.get("evidence_tier") or "").lower()
    if tier and tier not in ALLOWED_EVIDENCE_TIERS:
        return [f"invalid evidence_tier: {tier!r}"]
    return []


def _rule_employee_count(payload: dict) -> list[str]:
    cnt = payload.get("organization_employee_count")
    if cnt is None:
        return []
    try:
        value = int(cnt)
    except (TypeError, ValueError):
        return [f"non-numeric organization_employee_count: {cnt!r}"]
    if value < 0:
        return [f"negative organization_employee_count: {value}"]
    return []


def _rule_outcomes(payload: dict) -> list[str]:
    outcomes = payload.get("outcomes") or []
    if not isinstance(outcomes, list):
        return ["outcomes must be a list"]
    issues = []
    for i, o in enumerate(outcomes):
        if not isinstance(o, dict):
            issues.append(f"outcomes[{i}] is not an object")
            continue
        if not _has_content(o.get("metric_name"), 1):
            issues.append(f"outcomes[{i}] missing metric_name")
    return issues


def _rule_outcome_block(payload: dict) -> list[str]:
    block = payload.get("outcome_block") or {}
    if not isinstance(block, dict) or not block:
        return []
    pct = block.get("percent_change")
    if pct is None:
        return []
    if isinstance(pct, bool):
        return ["outcome_block.percent_change must be numeric or null"]
    if isinstance(pct, (int, float)):
        return []
    return ["outcome_block.percent_change must be numeric or null"]


RULES: list[tuple[str, Rule]] = [
    ("required_fields", _rule_required_fields),
    ("intervention_category", _rule_intervention_category),
    ("evidence_tier", _rule_evidence_tier),
    ("employee_count", _rule_employee_count),
    ("outcomes", _rule_outcomes),
    ("outcome_block", _rule_outcome_block),
]


def validate_enrichment(payload: dict) -> ValidationReport:
    """Validate a single enriched payload against all rules."""
    issues: list[str] = []
    checks: dict[str, bool] = {}
    for name, rule in RULES:
        rule_issues = rule(payload or {})
        checks[name] = not rule_issues
        issues.extend(rule_issues)
    return ValidationReport(valid=not issues, issues=issues, checks=checks)
