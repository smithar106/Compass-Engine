"""Context-aware retrieval factors (Phase 6).

Replaces the single coarse "industry" similarity with separate fit factors:
problem, workflow, operational-function, industry-subsector, broader-industry,
organization-size, business-model, geography, regulatory, and
technology-readiness. Workflow + problem fit dominate broad industry so useful
cross-industry implementations are not excluded.

Every comparable returns a per-factor breakdown so the reason for its ranking
is transparent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from compass_collector.organization.taxonomy import (
    employee_count_to_band,
    normalize_industry,
    regulatory_intensity_for,
)
from compass_collector.analysis.retrieval import (
    score_workflow_similarity,
    score_company_similarity,
)

# Factor weights. Workflow + problem = 0.46 vs industry (subsector+broader) = 0.18.
CONTEXT_FACTOR_WEIGHTS: dict[str, float] = {
    "problem": 0.24,
    "workflow": 0.22,
    "operational_function": 0.12,
    "industry_subsector": 0.10,
    "broader_industry": 0.08,
    "organization_size": 0.10,
    "business_model": 0.06,
    "geography": 0.04,
    "regulatory": 0.03,
    "technology_readiness": 0.01,
}

FACTOR_ORDER = [
    "problem",
    "workflow",
    "operational_function",
    "industry_subsector",
    "broader_industry",
    "organization_size",
    "business_model",
    "geography",
    "regulatory",
    "technology_readiness",
]

_BUSINESS_FUNCTION_ALIASES = {
    "customer_support": {"support", "customer_service", "service"},
    "human_resources": {"hr", "people"},
    "supply_chain": {"supply chain", "logistics"},
    "operations": {"ops", "back office"},
}


@dataclass
class ContextQuery:
    workflow: str = ""
    business_function: str = ""
    problem_statement: str = ""
    primary_industry: str = ""
    industry_subsector: str = ""
    broader_industry: str = ""
    employee_count: Optional[int] = None
    employee_band: str = ""
    business_model: str = ""
    geography: str = ""
    regulatory_context: str = ""
    technology_readiness: str = ""

    @classmethod
    def from_profile(cls, org_profile: Optional[dict], assessment: Any = None) -> "ContextQuery":
        """Build a query from a resolved organization profile + assessment."""
        q = cls()
        if assessment is not None:
            q.workflow = getattr(assessment, "workflow", "") or ""
            q.business_function = getattr(assessment, "business_function", "") or ""
            q.problem_statement = getattr(assessment, "problem_statement", "") or ""
        fields = {}
        if org_profile:
            # ResolveResult dicts wrap the profile under ``proposed``.
            if isinstance(org_profile, dict) and org_profile.get("proposed"):
                org_profile = org_profile["proposed"]
            fields = (org_profile.get("fields") or {}) if isinstance(org_profile, dict) else {}
        q.primary_industry = _field(fields, "primary_industry")
        q.industry_subsector = _field(fields, "industry_subsector")
        q.broader_industry = _field(fields, "broader_industry")
        q.business_model = _field(fields, "business_model")
        q.geography = _field(fields, "headquarters_country") or _field(fields, "geography")
        q.regulatory_context = _field(fields, "regulatory_context")
        q.technology_readiness = _field(fields, "technology_posture")
        emp = _field(fields, "employee_count")
        if emp:
            try:
                q.employee_count = int(float(emp))
            except (TypeError, ValueError):
                pass
        q.employee_band = _field(fields, "employee_band") or (employee_count_to_band(q.employee_count) or "")
        return q


def _field(fields: dict, name: str) -> str:
    entry = fields.get(name)
    if not entry:
        return ""
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry or "")


@dataclass
class ContextFitResult:
    total: float = 0.0
    max_possible: float = sum(CONTEXT_FACTOR_WEIGHTS.values())
    factors: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 3),
            "max_possible": round(self.max_possible, 3),
            "factors": {
                name: {"raw": round(v["raw"], 2), "weighted": round(v["weighted"], 3)}
                for name, v in self.factors.items()
            },
        }


def _business_function_fit(query: str, record_functions: list[str]) -> float:
    """Match on real values; neutral (0.5) when the record has no function data
    so sparse coverage does not penalize records that lack the field."""
    if not query:
        return 0.0
    if not record_functions:
        return 0.5
    q = query.strip().lower()
    for rf in record_functions:
        r = str(rf).strip().lower()
        if r == q:
            return 1.0
        q_aliases = _BUSINESS_FUNCTION_ALIASES.get(r, set())
        if q in q_aliases or r in _BUSINESS_FUNCTION_ALIASES.get(q, set()):
            return 0.8
    return 0.0


def _industry_subsector_fit(query_sub: str, query_primary: str, record_sub: str, record_primary: str) -> float:
    if not query_primary or not record_primary:
        return 0.0
    if query_primary == record_primary:
        if query_sub and record_sub and query_sub == record_sub:
            return 1.0
        if query_sub and record_sub:
            return 0.5
        return 0.7
    return 0.0


def _broader_industry_fit(q: str, record_industries: list[str]) -> float:
    if not q:
        return 0.0
    for r in record_industries:
        if r == q:
            return 1.0
        # word overlap across canonical keys ("financial_services" vs "banking")
        q_words = set(re.sub(r"[_\-]", " ", q).split())
        r_words = set(re.sub(r"[_\-]", " ", r).split())
        if q_words & r_words:
            return 0.5
    return 0.0


def _size_fit(query: ContextQuery, record: Any) -> float:
    """Size-band fit. Rewards exact/adjacent matches, neutral (0.5) when the
    record has no size data so the factor promotes as coverage rises."""
    if not (query.employee_band or query.employee_count):
        return 0.0
    rec_count = getattr(record, "organization_employee_count", None)
    rec_band = getattr(record, "organization_employee_band", "") or (employee_count_to_band(rec_count) or "")
    q_band = query.employee_band or (employee_count_to_band(query.employee_count) or "")
    if not rec_band:
        return 0.5  # record lacks size data → neutral, not a penalty
    bands = ["<10", "10-50", "50-200", "200-1000", "1000-10000", "10000+"]
    if q_band in bands and rec_band in bands:
        dist = abs(bands.index(q_band) - bands.index(rec_band))
        if dist == 0:
            return 1.0
        if dist == 1:
            return 0.6
        if dist == 2:
            return 0.3
    return 0.0


def _geo_fit(q: str, record_geographies: list[str]) -> float:
    if not q:
        return 0.0
    if not record_geographies:
        return 0.5  # record lacks geography → neutral
    qk = q.strip().lower()
    for g in record_geographies:
        gk = str(g).strip().lower()
        if qk == gk or qk in gk or gk in qk:
            return 1.0
    return 0.0


def _regulatory_fit(q: str, record_industry: Optional[str]) -> float:
    if not q:
        return 0.0
    if not record_industry:
        return 0.5  # cannot assess → neutral
    rec_reg = regulatory_intensity_for(record_industry)
    return 1.0 if rec_reg == q else 0.0


def compute_context_similarity(query: ContextQuery, record: Any, metrics: list = None) -> ContextFitResult:
    """Compute the ten-factor fit between a query profile and a record."""
    result = ContextFitResult()

    # Normalize the record's industry(s) to canonical form.
    raw_industries = getattr(record, "organization_industry", None) or []
    if isinstance(raw_industries, str):
        raw_industries = [raw_industries]
    norms = [normalize_industry(str(i)) for i in raw_industries if i]
    record_canonicals = [n.canonical for n in norms if n.mapped]
    record_subsectors = [n.subsector for n in norms if n.mapped]

    def _add(name: str, raw: float) -> None:
        result.factors[name] = {
            "raw": round(min(1.0, max(0.0, raw)), 3),
            "weighted": round(min(1.0, max(0.0, raw)) * CONTEXT_FACTOR_WEIGHTS[name], 4),
        }

    # problem fit: token overlap between query problem and record problem text
    q_text = (query.problem_statement or query.workflow or "").lower()
    rec_parts = []
    for attr in ("problem_statement", "problem_baseline_description", "intervention_title", "intervention_description"):
        val = getattr(record, attr, None)
        if val:
            rec_parts.append(str(val).lower())
    rec_text = " ".join(rec_parts)
    if q_text and rec_text:
        q_words = set(re.findall(r"[a-z0-9]+", q_text))
        r_words = set(re.findall(r"[a-z0-9]+", rec_text))
        overlap = len(q_words & r_words)
        problem_raw = overlap / max(len(q_words), 1) if q_words else 0.0
        problem_raw = min(1.0, problem_raw * 1.5)
    else:
        problem_raw = 0.0
    _add("problem", problem_raw)

    # workflow fit
    record_workflow = ""
    comps = getattr(record, "intervention_components", None)
    if isinstance(comps, dict):
        record_workflow = str(comps.get("workflow") or "")
    wf_raw = score_workflow_similarity(query.workflow, record_workflow)
    # keyword containment: query slugs ("invoice_processing") vs free-text record
    # workflows ("Order Entry, Invoicing...") — a significant query term present
    # in the record workflow text is a strong workflow signal.
    if query.workflow and record_workflow:
        q_terms = [t for t in re.split(r"[_\-\s]+", query.workflow.lower()) if len(t) >= 4]
        r_lower = record_workflow.lower()
        if q_terms and any(t in r_lower for t in q_terms):
            wf_raw = max(wf_raw, 0.9)
    _add("workflow", wf_raw)

    # operational-function fit
    funcs = getattr(record, "problem_business_function", None) or []
    _add("operational_function", _business_function_fit(query.business_function, funcs))

    # industry-subsector + broader-industry fit
    rec_sub = record_subsectors[0] if record_subsectors else ""
    rec_primary = record_canonicals[0] if record_canonicals else ""
    _add("industry_subsector", _industry_subsector_fit(
        query.industry_subsector, query.primary_industry, rec_sub, rec_primary))
    _add("broader_industry", _broader_industry_fit(query.primary_industry, record_canonicals))

    # organization-size fit
    _add("organization_size", _size_fit(query, record))

    # business-model fit (neutral 0.5 when either side unknown — do not punish)
    rec_model = getattr(record, "organization_type", None) or ""
    if query.business_model and rec_model:
        bm = 1.0 if str(rec_model).strip().lower() == query.business_model.lower() else 0.4
    else:
        bm = 0.5
    _add("business_model", bm)

    # geography fit
    geos = getattr(record, "organization_geography", None) or []
    _add("geography", _geo_fit(query.geography, geos))

    # regulatory fit
    _add("regulatory", _regulatory_fit(query.regulatory_context, rec_primary))

    # technology-readiness fit (neutral when unknown)
    if query.technology_readiness:
        _add("technology_readiness", 1.0 if str(getattr(record, "organization_type", "") or "").strip().lower() == query.technology_readiness.lower() else 0.5)
    else:
        _add("technology_readiness", 0.5)

    result.total = sum(v["weighted"] for v in result.factors.values())
    return result


def find_comparable_implementations_context(
    query: ContextQuery,
    records: list,
    metrics_by_id: Optional[dict] = None,
    min_total: float = 0.02,
    max_results: int = 20,
    include_negative: bool = True,
) -> dict:
    """Rank comparable implementations by context fit with a factor breakdown.

    Workflow + problem dominate; cross-industry records are not excluded purely
    because the industry differs. Returns a dict with per-record factors.
    """
    metrics_by_id = metrics_by_id or {}
    scored = []
    for rec in records:
        if not include_negative and getattr(rec, "result_status", "") in ("failed", "abandoned"):
            continue
        metrics = metrics_by_id.get(getattr(rec, "id", ""), [])
        fit = compute_context_similarity(query, rec, metrics)
        if fit.total <= 0:
            continue
        scored.append({"fit": fit, "record": rec, "metrics": metrics})

    scored.sort(key=lambda s: -s["fit"].total)

    seen_orgs = set()
    results = []
    for s in scored:
        org = (getattr(s["record"], "organization_name", "") or "").strip().lower()
        if org and org in seen_orgs:
            continue
        seen_orgs.add(org)
        results.append(s)
        if len(results) >= max_results:
            break

    return {
        "query": {
            "workflow": query.workflow,
            "business_function": query.business_function,
            "primary_industry": query.primary_industry,
            "industry_subsector": query.industry_subsector,
            "employee_band": query.employee_band,
            "geography": query.geography,
        },
        "total_scored": len(scored),
        "results": [
            {
                "id": getattr(s["record"], "id", ""),
                "organization": getattr(s["record"], "organization_name", "") or "Unknown",
                "industry": getattr(s["record"], "organization_industry", None) or [],
                "intervention": getattr(s["record"], "intervention_title", "") or "",
                "status": getattr(s["record"], "result_status", "") or "unknown",
                "fit_total": round(s["fit"].total, 3),
                "fit_breakdown": s["fit"].to_dict()["factors"],
            }
            for s in results
        ],
    }

