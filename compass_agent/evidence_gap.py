"""Evidence Gap Engine v2 — the nightly shopping list.

Answers, per decision category (workflow × business function):
  * which decisions are weakest and why (volume, tier depth, field coverage)
  * how defensible the evidence is (diversity: vendors, industries, tech
    families, geographies, size bands)
  * exactly what to hunt (targets + composed search terms + source-library
    priority) — the shopping list Discovery executes first.

Deterministic and pure: same data in → same report out. No LLM in the scoring
path. Demand is measured (analyze/outcome query telemetry, passed as
``demand_override``) with a keyword fallback for categories lacking telemetry.

Spec: docs/evidence_gap_engine.md
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from compass_agent.gap_analysis import (
    BUSINESS_CATEGORY_KEYWORDS,
    DEFAULT_DEMAND,
    FIELD_COVERAGE_TARGET,
    IMPLEMENTATION_FIELDS,
    MIN_COMPARABLES,
    MIN_GOLD,
    MIN_SILVER,
    _keyword_demand,
    _workflow_slug,
)

ENGINE_VERSION = "gap-engine-v2"

# Coverage level thresholds (mirror compass_collector/api/coverage_router.py).
EXCELLENT_SOFT = 25
GOOD_SOFT = 10
DEV_MIN = 4

HIGH_QUALITY_TIERS = ("gold", "decision_grade")

# Vendor concentration is meaningful only when there are enough samples.
MIN_VENDOR_DIVERSITY_SAMPLE = 5
CONCENTRATION_SHARE = 0.6

# Fallback vendor candidates for diversity hunts (global top vendors).
GLOBAL_VENDOR_CANDIDATES = [
    "oracle", "aws", "google_cloud", "microsoft", "salesforce", "sap",
    "ibm", "uipath", "automation_anywhere", "servicenow", "snowflake",
    "databricks", "adobe", "atlassian", "zendesk", "nvidia",
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", str(text or "").strip().lower()).strip("_")


def _record_workflow(rec: Any) -> str:
    # Canonical workflow (Phase 4 backfill) wins when present.
    wn = getattr(rec, "workflow_normalized", None) or {}
    if isinstance(wn, dict) and wn.get("value"):
        return str(wn["value"])
    # Otherwise normalize the stored free-text workflow, or infer from text.
    from compass_collector.organization.workflow_taxonomy import infer_workflow, normalize_workflow

    comps = getattr(rec, "intervention_components", None) or {}
    if isinstance(comps, dict):
        wf = comps.get("workflow") or ""
        if wf:
            nv = normalize_workflow(str(wf).strip())
            if nv.value:
                return nv.value
    text = " ".join(
        str(x).strip() for x in
        (getattr(rec, "intervention_title", "") or "", getattr(rec, "problem_statement", "") or "")
        if x
    )
    if text:
        nv = infer_workflow(text)
        if nv.value:
            return nv.value
    bf = getattr(rec, "problem_business_function", None) or []
    if bf:
        return str(bf[0]).strip()
    return "uncategorized"


def _record_function(rec: Any) -> str:
    # Canonical workflow implies its business function.
    wn = getattr(rec, "workflow_normalized", None) or {}
    if isinstance(wn, dict) and wn.get("function"):
        return str(wn["function"])
    bf = getattr(rec, "problem_business_function", None) or []
    if not bf:
        return "operations"
    raw = str(bf[0]).strip()
    # Collapse free-text/multi-label functions onto the canonical set
    # (e.g. "Human Resources / Recruiting" → human_resources,
    #  "customer_support, marketing, operations" → customer_support).
    from compass_collector.organization.taxonomy import normalize_operational_function

    if "," in raw:
        raw = raw.split(",")[0].strip()
    nv = normalize_operational_function(raw)
    return nv.value or "operations"


def _record_tier(rec: Any) -> str:
    """Map stored review_status onto the decision taxonomy."""
    t = str(getattr(rec, "review_status", "") or "").lower()
    if t == "decision_grade" or t == "gold":
        return t
    if t == "silver":  # legacy
        return "decision_grade"
    if t == "bronze":  # legacy
        return "supporting"
    # Fall back to the evidence_level column for older snapshots.
    el = str(getattr(rec, "evidence_level", "") or "").lower()
    if el == "gold":
        return "gold"
    if el in ("silver", "decision_grade"):
        return "decision_grade"
    return "supporting"


def _has_field(rec: Any, field: str) -> bool:
    value = getattr(rec, field, None)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _norm_entries(rec: Any, column: str) -> list[dict]:
    raw = getattr(rec, column, None) or {}
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    if isinstance(raw, dict):
        return [e for e in raw.values() if isinstance(e, dict)]
    return []


def _norm_values(rec: Any, column: str, min_conf: float = 0.7) -> list[str]:
    return [
        str(e.get("value", "")).strip()
        for e in _norm_entries(rec, column)
        if e.get("confidence", 0) >= min_conf and e.get("value")
    ]


def coverage_level(total_high: int, ratio: float) -> str:
    """Derive a coverage label from high-quality count and ratio."""
    if total_high == 0:
        return "absent"
    if total_high >= EXCELLENT_SOFT and ratio >= 0.25:
        return "excellent"
    if total_high >= GOOD_SOFT or ratio >= 0.5:
        return "good"
    if total_high >= DEV_MIN or ratio >= 0.1:
        return "developing"
    return "limited"


# ---------------------------------------------------------------------------
# Diversity
# ---------------------------------------------------------------------------


def diversity_stats(records: list[Any]) -> dict:
    """Vendor/industry/tech/geo/size diversity for a category's records."""
    vendors: Counter = Counter()
    industries: Counter = Counter()
    families: Counter = Counter()
    geos: Counter = Counter()
    bands: Counter = Counter()
    vendored_records = 0

    for rec in records:
        vs = _norm_values(rec, "intervention_vendors_normalized")
        if vs:
            vendored_records += 1
            vendors.update(vs)
        ind = (rec.organization_normalized or {}).get("primary_industry")
        if isinstance(ind, dict) and ind.get("value"):
            industries[ind["value"]] += 1
        for fam in {
            e.get("family")
            for e in _norm_entries(rec, "intervention_software_normalized")
            if e.get("confidence", 0) >= 0.7 and e.get("family")
        }:
            families[fam] += 1
        geo = (rec.organization_normalized or {}).get("geography")
        if isinstance(geo, dict) and geo.get("value"):
            geos[geo["value"]] += 1
        emp = (rec.organization_normalized or {}).get("employee_count")
        if isinstance(emp, dict) and emp.get("value"):
            bands[emp["value"]] += 1

    top_vendor, top_vendor_n = (vendors.most_common(1) or [(None, 0)])[0]
    share = round(top_vendor_n / max(vendored_records, 1), 3) if top_vendor else 0.0
    concentration = bool(
        top_vendor and vendored_records >= MIN_VENDOR_DIVERSITY_SAMPLE and share > CONCENTRATION_SHARE
    )
    return {
        "vendors": len(vendors),
        "top_vendor": top_vendor,
        "top_vendor_share": share,
        "concentration": concentration,
        "industries": len(industries),
        "tech_families": len(families),
        "geographies": len(geos),
        "employee_bands": len(bands),
        "vendored_records": vendored_records,
        "present_vendors": list(vendors.keys()),
        "present_industries": list(industries.keys()),
        "present_families": list(families.keys()),
        "present_geographies": list(geos.keys()),
    }


def _top_absent(global_counter: Counter, present: set, k: int = 3) -> list[str]:
    return [v for v, _ in global_counter.most_common(50) if v not in present][:k]


# ---------------------------------------------------------------------------
# EvidenceNeed
# ---------------------------------------------------------------------------


@dataclass
class EvidenceNeed:
    workflow: str
    business_function: str
    total_records: int = 0
    decision_grade: int = 0
    gold: int = 0
    supporting: int = 0
    field_coverage: dict = field(default_factory=dict)
    missing_fields: list = field(default_factory=list)
    demand: float = 0.0
    gap_score: float = 0.0
    expected_impact: float = 0.0
    estimated_records_needed: int = 0
    decision_coverage: str = "absent"
    diversity: dict = field(default_factory=dict)
    # The shopping list
    target_industries: list = field(default_factory=list)
    target_employee_bands: list = field(default_factory=list)
    target_geographies: list = field(default_factory=list)
    target_tech_families: list = field(default_factory=list)
    vendor_diversity_target: str = ""
    search_terms: list = field(default_factory=list)
    source_library_priority: list = field(default_factory=list)
    data_limited_fields: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "business_function": self.business_function,
            "decision_coverage": self.decision_coverage,
            "gap_score": round(self.gap_score, 3),
            "demand": round(self.demand, 3),
            "expected_impact": round(self.expected_impact, 3),
            "comparables": self.total_records,
            "decision_grade": self.decision_grade,
            "gold": self.gold,
            "supporting": self.supporting,
            "missing_fields": self.missing_fields,
            "estimated_records_needed": self.estimated_records_needed,
            "diversity": self.diversity,
            "shopping_list": {
                "target_industries": self.target_industries,
                "target_employee_bands": self.target_employee_bands,
                "target_geographies": self.target_geographies,
                "target_tech_families": self.target_tech_families,
                "vendor_diversity_target": self.vendor_diversity_target,
                "search_terms": self.search_terms,
                "source_library_priority": self.source_library_priority,
            },
            "data_limited_fields": self.data_limited_fields,
        }


# ---------------------------------------------------------------------------
# Composition (search terms + library priority)
# ---------------------------------------------------------------------------


def compose_search_terms(need: EvidenceNeed) -> list[str]:
    """Deterministic, category-specific hunt queries."""
    wf = need.workflow
    fn = need.business_function
    terms = [f"{wf} {fn} implementation"]

    if need.gold == 0:
        terms.append(f"{wf} automation quantified results")
    if need.decision_grade < MIN_SILVER:
        terms.append(f"{wf} {fn} case study outcomes")

    d = need.diversity or {}
    if d.get("concentration") and d.get("top_vendor"):
        alts = [v for v in GLOBAL_VENDOR_CANDIDATES if v not in set(d.get("present_vendors", []))][:3]
        if alts:
            terms.append(f"{wf} {' OR '.join(alts)} case study")
    for mf in need.missing_fields[:1]:
        terms.append(f"{wf} {mf.replace('_', ' ')}")
    if need.target_industries:
        terms.append(f"{wf} {need.target_industries[0].replace('_', ' ')} case study")
    # Deduplicate, cap at 5
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:5]


def score_libraries(need: EvidenceNeed, registry: list[dict], top_n: int = 3) -> list[str]:
    """Rank source libraries by relevance to this need (deterministic)."""
    wf_words = set(_slug(need.workflow).split("_"))
    fn_slug = _slug(need.business_function)

    scored = []
    for lib in registry:
        text = " ".join(
            [str(lib.get("name", "")), str(lib.get("category", "")), " ".join(lib.get("entry_urls", []))]
        ).lower()
        score = sum(1 for w in wf_words if w and len(w) > 2 and w in text)
        if fn_slug in text or fn_slug.replace("_", " ") in text:
            score += 2
        # category affinity
        if lib.get("category") == "government" and fn_slug in ("operations", "customer_support", "it"):
            score += 1
        if lib.get("category") == "public_company" and fn_slug in ("finance", "accounting", "legal"):
            score += 2
        if lib.get("category") == "academic" and "research" in fn_slug:
            score += 1
        scored.append((score, lib.get("id", "")))

    scored.sort(key=lambda x: -x[0])
    hits = [lid for s, lid in scored if s > 0][:top_n]
    if len(hits) < top_n:
        # Pad with estimated-quality fallback (never duplicate ids).
        fallback = sorted(registry, key=lambda l: -float(l.get("estimated_quality", 0.5)))
        for lib in fallback:
            if len(hits) >= top_n:
                break
            lid = str(lib.get("id", ""))
            if lid not in hits:
                hits.append(lid)
    return hits


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _gap_score(total: int, gold: int, decision_grade: int, coverage: dict) -> float:
    """Weighted deficit vs evidence targets, 0 healthy → 1 critical."""
    scores = [
        min(1.0, (MIN_COMPARABLES - total) / MIN_COMPARABLES),
        min(1.0, (MIN_GOLD - gold) / MIN_GOLD),
        min(1.0, (MIN_SILVER - decision_grade) / MIN_SILVER),
    ]
    for field, cov in coverage.items():
        scores.append(max(0.0, (FIELD_COVERAGE_TARGET - cov) / FIELD_COVERAGE_TARGET))
    return sum(scores) / max(len(scores), 1)


def _category_need(
    workflow: str,
    fn: str,
    records: list[Any],
    demand: float,
    global_industries: Counter,
    global_families: Counter,
    global_geos: Counter,
    global_bands: Counter,
) -> EvidenceNeed:
    total = len(records)
    gold = sum(1 for r in records if _record_tier(r) == "gold")
    decision_grade = sum(1 for r in records if _record_tier(r) == "decision_grade")
    supporting = total - gold - decision_grade

    coverage = {f: _coverage_frac(records, f) for f in IMPLEMENTATION_FIELDS}
    missing = [f for f, cov in coverage.items() if cov < FIELD_COVERAGE_TARGET]
    gap = _gap_score(total, gold, decision_grade, coverage)
    need = max(0, MIN_COMPARABLES - total) + max(0, MIN_GOLD - gold) + max(0, MIN_SILVER - decision_grade)
    high_total = gold + decision_grade
    ratio = high_total / total if total else 0.0
    coverage_label = "absent" if total == 0 else coverage_level(high_total, ratio)

    div = diversity_stats(records)
    # Sparse dimensions: express as preferences, flag as data-limited.
    data_limited = []
    targets_geo = []
    targets_bands = []
    targets_families = []
    if div["geographies"] < 3:
        targets_geo = _top_absent(global_geos, set(div["present_geographies"]), 3)
        data_limited.append("geography")
    if div["employee_bands"] < 3:
        targets_bands = _top_absent(global_bands, set(), 3)
        data_limited.append("employee_band")
    if div["tech_families"] < 3:
        targets_families = _top_absent(global_families, set(div["present_families"]), 3)

    vendor_target = ""
    if div["concentration"]:
        vendor_target = (
            f"add >=3 distinct vendors outside {div['top_vendor']} "
            f"(top-1 share {div['top_vendor_share']:.0%})"
        )

    need_obj = EvidenceNeed(
        workflow=workflow,
        business_function=fn,
        total_records=total,
        decision_grade=decision_grade,
        gold=gold,
        supporting=supporting,
        field_coverage={k: round(v, 2) for k, v in coverage.items()},
        missing_fields=missing,
        demand=round(demand, 3),
        gap_score=round(gap, 3),
        expected_impact=round(gap * demand, 3),
        estimated_records_needed=need,
        decision_coverage=coverage_label,
        diversity=div,
        target_industries=_top_absent(global_industries, set(div["present_industries"]), 3),
        target_employee_bands=targets_bands,
        target_geographies=targets_geo,
        target_tech_families=targets_families,
        vendor_diversity_target=vendor_target,
        data_limited_fields=data_limited,
    )
    need_obj.search_terms = compose_search_terms(need_obj)
    return need_obj


def _coverage_frac(records: list[Any], field: str) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if _has_field(r, field)) / len(records)


def _demand_for(workflow: str, demand_override: dict) -> float:
    slug = _workflow_slug(workflow)
    if slug in demand_override:
        return float(demand_override[slug])
    return max(_keyword_demand(workflow), DEFAULT_DEMAND.get(slug, 0.4))


@dataclass
class GapReport:
    generated_at: str
    engine_version: str = ENGINE_VERSION
    total_records: int = 0
    categories: int = 0
    needs: list = field(default_factory=list)
    shopping_list: list = field(default_factory=list)
    decision_coverage_by_function: dict = field(default_factory=dict)
    dimension_coverage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "engine_version": self.engine_version,
            "total_records": self.total_records,
            "categories": self.categories,
            "decision_coverage_by_function": self.decision_coverage_by_function,
            "dimension_coverage": self.dimension_coverage,
            "needs": [n.to_dict() for n in self.needs],
            "shopping_list": [n.to_dict() for n in self.shopping_list],
        }


def run_gap_engine(
    session=None,
    top_n: int = 10,
    min_impact: float = 0.0,
    demand_override: Optional[dict] = None,
) -> GapReport:
    """Score every decision category and produce the ranked shopping list.

    ``session`` — SQLAlchemy session over the collector DB (created from
    settings if None). ``demand_override`` — workflow-slug → demand telemetry
    (analyze/outcome query volume); categories without telemetry use keyword
    fallback.
    """
    if session is None:
        from compass_collector.database import get_session

        session = get_session()
    from compass_collector.models.intervention import InterventionRecord

    records = session.query(InterventionRecord).all()
    demand_override = demand_override or {}

    grouped: dict[tuple, list] = defaultdict(list)
    for rec in records:
        grouped[(_record_workflow(rec), _record_function(rec))].append(rec)

    # Global canonical distributions for target composition.
    global_industries: Counter = Counter()
    global_families: Counter = Counter()
    global_geos: Counter = Counter()
    global_bands: Counter = Counter()
    for rec in records:
        ind = (rec.organization_normalized or {}).get("primary_industry")
        if isinstance(ind, dict) and ind.get("value"):
            global_industries[ind["value"]] += 1
        for e in _norm_entries(rec, "intervention_software_normalized"):
            if e.get("confidence", 0) >= 0.7 and e.get("family"):
                global_families[e["family"]] += 1
        geo = (rec.organization_normalized or {}).get("geography")
        if isinstance(geo, dict) and geo.get("value"):
            global_geos[geo["value"]] += 1
        emp = (rec.organization_normalized or {}).get("employee_count")
        if isinstance(emp, dict) and emp.get("value"):
            global_bands[emp["value"]] += 1

    needs: list[EvidenceNeed] = []
    for (workflow, fn), recs in grouped.items():
        need_obj = _category_need(
            workflow, fn, recs,
            _demand_for(workflow, demand_override),
            global_industries, global_families, global_geos, global_bands,
        )
        need_obj.source_library_priority = score_libraries(need_obj, _library_registry())
        needs.append(need_obj)

    needs.sort(key=lambda n: -n.expected_impact)

    # Decision Coverage KPI: per function, demand-weighted share of categories
    # at good+ coverage.
    by_function: dict[str, dict] = defaultdict(lambda: {"weighted_covered": 0.0, "weighted_total": 0.0, "categories": 0, "good_plus": 0})
    for n in needs:
        agg = by_function[n.business_function]
        agg["categories"] += 1
        agg["weighted_total"] += max(n.demand, 0.01)
        if n.decision_coverage in ("good", "excellent"):
            agg["good_plus"] += 1
            agg["weighted_covered"] += max(n.demand, 0.01)
    decision_coverage_by_function = {
        fn: {
            "coverage_pct": round(100 * agg["weighted_covered"] / max(agg["weighted_total"], 1e-9), 1),
            "categories": agg["categories"],
            "good_plus": agg["good_plus"],
        }
        for fn, agg in sorted(by_function.items(), key=lambda kv: -kv[1]["weighted_total"])
    }

    # Dimension coverage across the whole graph.
    n = len(records)
    with_workflow = sum(
        1 for r in records
        if isinstance(getattr(r, "workflow_normalized", None), dict)
        and (r.workflow_normalized or {}).get("confidence", 0) >= 0.5
    )
    dims = {
        "canonical_industry": sum(1 for r in records if (r.organization_normalized or {}).get("primary_industry")),
        "canonical_vendor": sum(1 for r in records if _norm_values(r, "intervention_vendors_normalized")),
        "canonical_technology": sum(1 for r in records if _norm_values(r, "intervention_software_normalized")),
        "geography": sum(1 for r in records if (r.organization_normalized or {}).get("geography")),
        "employee_count": sum(1 for r in records if (r.organization_normalized or {}).get("employee_count")),
        "workflow": with_workflow,
    }
    dimension_coverage = {k: {"n": v, "pct": round(100 * v / max(n, 1), 1)} for k, v in dims.items()}

    shopping = [n for n in needs if n.expected_impact >= min_impact][:top_n]
    return GapReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_records=n,
        categories=len(needs),
        needs=needs,
        shopping_list=shopping,
        decision_coverage_by_function=decision_coverage_by_function,
        dimension_coverage=dimension_coverage,
    )


def _library_registry() -> list[dict]:
    from compass_agent.libraries import LIBRARY_REGISTRY

    return LIBRARY_REGISTRY


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_report(report: GapReport, gaps_dir: Optional[Path] = None) -> dict[str, Path]:
    """Persist the full report + shopping list to ``data/gaps/``."""
    from compass_collector.config.settings import DATA_DIR

    out_dir = gaps_dir or (Path(DATA_DIR) / "gaps")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "evidence_gap_report.json"
    shopping_path = out_dir / "shopping_list.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2))
    shopping_path.write_text(
        json.dumps({"generated_at": report.generated_at, "engine_version": report.engine_version,
                    "shopping_list": [n.to_dict() for n in report.shopping_list]}, indent=2)
    )
    return {"report": report_path, "shopping_list": shopping_path}
