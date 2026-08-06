"""Quality-first evidence operations: Bronze audit + Silver→Gold promotion.

Mirrors the engine's evidence-tier classifier (``compass_collector/api/evidence_tier.py``)
so the agent can reason about *why* a record is Bronze and what a Silver record
still needs to reach Gold — then plan and (optionally) apply targeted
enrichment that fills only the missing scored components, instead of
re-extracting the whole page.

Components
    audit   classify every Bronze record into a primary reason bucket
    plan    rank Silver records by points-gap to Gold and fillability
    apply   re-enrich the top candidates for their missing components and sync
            the result to the engine via ``POST /api/evidence/enrichment``
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("compass_agent.promote")

# ── Gold-score card (must stay aligned with the engine classifier) ──────

# Components that an LLM can plausibly recover from the source document.
FILLABLE_COMPONENTS = {
    "has_measurable_outcome",
    "has_baseline",
    "has_timeframe",
    "has_sample_size",
}

GOLD_THRESHOLD = 8
SILVER_THRESHOLD = 4
BRONZE_THRESHOLD = 1

NON_DEPLOYED_STATUSES = {"unknown", "theoretical", "proposed"}
ACADEMIC_KEYWORDS = ["university", "college", "institute of", "school of", "research lab", "academic"]


def compute_points(record: dict) -> dict:
    """Compute the engine's evidence-tier points for a record.

    ``record`` is a dict of model-column keys (see ``load_records``) plus an
    optional ``metrics`` list. Returns component booleans, subtotal, and the
    resulting tier so audit + planner share one source of truth.
    """
    org = (record.get("organization_name") or "").strip()
    anonymized = bool(record.get("organization_anonymized"))
    has_real_org = bool(org and not anonymized)

    status = (record.get("result_status") or "").lower().strip()
    was_deployed = status not in NON_DEPLOYED_STATUSES

    metrics = record.get("metrics") or []
    has_measurable_outcome = _has_quantified_metric(metrics)

    has_source_link = bool(record.get("source_id") or record.get("passages"))

    has_baseline = bool(record.get("has_baseline")) or bool(record.get("problem_baseline_description"))
    has_timeframe = bool(record.get("intervention_measurement_period_value"))
    sample = record.get("sample_size")
    has_sample_size = sample is not None and (isinstance(sample, (int, float)) and sample > 1)
    is_independent = bool(record.get("independently_verified"))
    is_vendor = bool(record.get("vendor_reported"))

    components = {
        "has_real_org": has_real_org,
        "was_deployed": was_deployed,
        "has_measurable_outcome": has_measurable_outcome,
        "has_source_link": has_source_link,
        "has_baseline": has_baseline,
        "has_timeframe": has_timeframe,
        "has_sample_size": has_sample_size,
        "is_independent": is_independent,
    }
    score = 0
    if has_real_org:
        score += 2
    if was_deployed:
        score += 2
    if has_measurable_outcome:
        score += 2
    if has_source_link:
        score += 1
    if has_baseline:
        score += 1
    if has_timeframe:
        score += 1
    if has_sample_size:
        score += 1
    if is_independent:
        score += 2
    if is_vendor:
        score -= 2

    tier = _tier_from_score(score, org, is_independent)
    return {
        "components": components,
        "vendor_reported": is_vendor,
        "score": score,
        "tier": tier,
    }


def _tier_from_score(score: int, org: str, independent: bool) -> str:
    org_lower = (org or "").lower()
    if any(k in org_lower for k in ACADEMIC_KEYWORDS) and not independent:
        return "rejected"
    if score >= GOLD_THRESHOLD:
        return "gold"
    if score >= SILVER_THRESHOLD:
        return "silver"
    if score >= BRONZE_THRESHOLD:
        return "bronze"
    return "rejected"


def classify_tier(record: dict) -> str:
    """The engine-equivalent tier for a record dict."""
    return compute_points(record)["tier"]


def _has_quantified_metric(metrics: list) -> bool:
    for m in metrics:
        pct = m.get("percentage_change")
        if pct is not None:
            try:
                if float(pct) != 0:
                    return True
            except (TypeError, ValueError):
                continue
        abs_change = m.get("absolute_change")
        if abs_change not in (None, 0, "", "0"):
            return True
    return False


# ── Bronze audit ─────────────────────────────────────────────────────────

BRONZE_REASON_MISSING_OUTCOME = "missing_outcome_metrics"
BRONZE_REASON_WEAK_PROVENANCE = "weak_provenance"
BRONZE_REASON_THIN_IMPLEMENTATION = "incomplete_implementation_detail"
BRONZE_REASON_NEAR_DUPLICATE = "duplicate_or_near_duplicate"
BRONZE_REASON_UNSUPPORTED_CLAIMS = "unsupported_claims"

BRONZE_REASON_LABELS = {
    BRONZE_REASON_MISSING_OUTCOME: "no quantified outcome metric",
    BRONZE_REASON_WEAK_PROVENANCE: "weak provenance (no source link / provenance fields)",
    BRONZE_REASON_THIN_IMPLEMENTATION: "incomplete implementation detail",
    BRONZE_REASON_NEAR_DUPLICATE: "duplicate or near-duplicate evidence",
    BRONZE_REASON_UNSUPPORTED_CLAIMS: "unsupported claims (vendor-only, no baseline)",
}


def bronze_reasons(record: dict, siblings: Optional[list] = None) -> dict:
    """Classify why a record is Bronze. Returns a dict of reason → bool."""
    points = compute_points(record)
    reasons = {}

    reasons[BRONZE_REASON_MISSING_OUTCOME] = not points["components"]["has_measurable_outcome"]
    reasons[BRONZE_REASON_WEAK_PROVENANCE] = not (
        bool(record.get("source_id")) or bool(points["components"]["has_source_link"])
    ) or not (record.get("implementation_provenance") or record.get("outcome_provenance"))
    richness = (record.get("implementation_richness") or "").lower()
    reasons[BRONZE_REASON_THIN_IMPLEMENTATION] = richness in ("thin", "usable") or richness == ""
    reasons[BRONZE_REASON_UNSUPPORTED_CLAIMS] = bool(record.get("vendor_reported")) and not bool(
        record.get("independently_verified")
    )
    reasons[BRONZE_REASON_NEAR_DUPLICATE] = _is_near_duplicate(record, siblings or [])

    return reasons


def primary_bronze_reason(record: dict, siblings: Optional[list] = None) -> str:
    reasons = bronze_reasons(record, siblings)
    for name, flag in reasons.items():
        if flag:
            return name
    return "other"


def _is_near_duplicate(record: dict, siblings: list) -> bool:
    org = (record.get("organization_name") or "").strip().lower()
    title = (record.get("intervention_title") or "").strip().lower()
    if not org or not title:
        return False
    title_tokens = set(title.split())
    for other in siblings:
        if other is record:
            continue
        if (other.get("organization_name") or "").strip().lower() != org:
            continue
        other_title = (other.get("intervention_title") or "").strip().lower()
        overlap = title_tokens & set(other_title.split())
        if other_title and len(overlap) >= 2:
            return True
    return False


@dataclass
class BronzeAudit:
    total_bronze: int = 0
    reasons: Counter = field(default_factory=Counter)
    examples: dict = field(default_factory=dict)  # reason -> [record ids]

    def to_dict(self) -> dict:
        return {
            "total_bronze": self.total_bronze,
            "reasons": dict(self.reasons),
            "reason_labels": BRONZE_REASON_LABELS,
            "examples": {k: v[:5] for k, v in self.examples.items()},
        }


def audit_bronze(records: list) -> BronzeAudit:
    audit = BronzeAudit()
    bronze = [r for r in records if compute_points(r)["tier"] == "bronze"]
    audit.total_bronze = len(bronze)
    for rec in bronze:
        reason = primary_bronze_reason(rec, bronze)
        audit.reasons[reason] += 1
        audit.examples.setdefault(reason, []).append(rec.get("id", ""))
    return audit


# ── Promotion planning ───────────────────────────────────────────────────

@dataclass
class Promotion:
    record_id: str
    organization_name: str
    intervention_title: str
    current_score: int
    target_score: int
    gap: int
    missing: list
    fillable_missing: list
    non_fillable_missing: list
    rank: float = 0.0

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "organization_name": self.organization_name,
            "intervention_title": self.intervention_title,
            "current_score": self.current_score,
            "target_score": self.target_score,
            "gap": self.gap,
            "missing": self.missing,
            "fillable_missing": self.fillable_missing,
            "non_fillable_missing": self.non_fillable_missing,
            "rank": round(self.rank, 3),
        }


def plan_promotions(records: list, target: str = "gold") -> list[Promotion]:
    """Rank records of the tier below ``target`` by how close they are and how
    much of the remaining gap is fillable from source text.

    ``target`` is the tier whose threshold the record is short of (default
    ``gold`` — promotes Silver→Gold). Records whose remaining gap is dominated
    by non-fillable components (anonymized org, undepoyed, vendor-only) rank
    below records that just need a metric/baseline/timeframe/sample recovered.
    """
    target_threshold = GOLD_THRESHOLD if target == "gold" else SILVER_THRESHOLD
    target_tier = target
    promotions: list[Promotion] = []

    for rec in records:
        pts = compute_points(rec)
        if pts["tier"] == target_tier or pts["tier"] == "rejected":
            continue
        if pts["score"] >= target_threshold:
            continue  # already at/above target
        missing = [name for name, ok in pts["components"].items() if not ok]
        fillable = [m for m in missing if m in FILLABLE_COMPONENTS]
        non_fillable = [m for m in missing if m not in FILLABLE_COMPONENTS]
        gap = target_threshold - pts["score"]

        # Rank: close gap wins; among ties, more fillable wins; break ties by
        # the cheap-to-fill outcome metric.
        rank = gap - 0.01 * len(fillable) - 0.001 * int(pts["components"].get("has_measurable_outcome"))
        promotions.append(
            Promotion(
                record_id=rec.get("id", ""),
                organization_name=rec.get("organization_name", ""),
                intervention_title=rec.get("intervention_title", ""),
                current_score=pts["score"],
                target_score=target_threshold,
                gap=gap,
                missing=missing,
                fillable_missing=fillable,
                non_fillable_missing=non_fillable,
                rank=rank,
            )
        )

    promotions.sort(key=lambda p: p.rank)
    return promotions


# ── Targeted promotion (apply) ───────────────────────────────────────────

PROMOTION_SYSTEM_PROMPT = (
    "You extract implementation evidence for business ROI case studies. "
    "Given a source document and a list of evidence fields to recover, extract "
    "ONLY those fields. Return strict JSON with keys matching the requested "
    "field names. Omit any field not supported by the text."
)

# Maps the scored, fillable component to the JSON key the LLM should produce and
# the engine column it updates.
PROMOTION_FIELD_SPECS = {
    "has_measurable_outcome": {"llm_key": "outcomes"},
    "has_baseline": {"llm_key": "baseline", "apply": lambda v, text: _baseline_fields(v, text)},
    "has_timeframe": {"llm_key": "measurement_period", "apply": lambda v, text: _timeframe_fields(v, text)},
    "has_sample_size": {"llm_key": "sample_size", "apply": lambda v, text: _sample_fields(v, text)},
}


def promotion_prompt(record: dict, promotion: Promotion) -> str:
    """A focused prompt asking the LLM to recover ONLY the missing components."""
    specs = [PROMOTION_FIELD_SPECS[c] for c in promotion.fillable_missing]
    fields = [s["llm_key"] for s in specs] or ["no_fields"]
    return (
        f"Source document URL: {record.get('source_id') or ''}\n"
        f"Title: {record.get('intervention_title') or ''}\n"
        f"Organization: {record.get('organization_name') or ''}\n"
        f"Currently the record is missing these evidence components and they "
        f"may be present in the document: {', '.join(fields)}.\n"
        "Return JSON like: {\"outcomes\": [{\"metric_name\": ..., \"metric_category\": ..., "
        "\"percentage_change\": ..., \"absolute_change\": ..., \"unit\": ..., \"source_passage\": ...}], "
        "\"baseline\": \"...\", \"measurement_period\": {\"value\": ..., \"unit\": \"...\"}, "
        "\"sample_size\": ...}\n"
        "Set each key only if the text supports it. Empty object {\"no_fields\": true} "
        "if none of the requested fields appear."
    )


def promotion_fields(record: dict, promotion: Promotion, extraction: dict) -> dict:
    """Map a focused extraction back onto engine enrichment ``fields`` plus the
    metric rows to upsert. Returns ``(fields, metrics)``.

    The returned ``fields`` dict is POSTed to ``/api/evidence/enrichment`` (the
    engine applies columns that exist). Metric dicts ride along in ``metrics``
    so the engine can upsert MetricRecords. The engine's ``reclassify`` step
    recomputes ``evidence_level`` from the final state, so the agent only
    provides the raw recovery candidates.
    """
    fields: dict = {}
    metrics: list = []
    for component in promotion.fillable_missing:
        spec = PROMOTION_FIELD_SPECS[component]
        value = extraction.get(spec["llm_key"])
        if not value:
            continue
        if component == "has_measurable_outcome":
            recovered = _metrics_rows(value)
            metrics.extend(recovered)
            if recovered:
                fields["has_post_measurement"] = True
        else:
            applied = spec["apply"](value, "")
            if applied:
                fields.update(applied)
    if not fields and not metrics:
        return {}, []
    # Preview the resulting tier so the caller can decide whether to push.
    merged = dict(record)
    merged.update(fields)
    merged["metrics"] = (record.get("metrics") or []) + _merge_metrics(record.get("metrics") or [], metrics)
    preview = compute_points(merged)["tier"]
    fields["intervention_components"] = {
        **(record.get("intervention_components") or {}),
        "evidence_tier": preview,
        "source_generation": "agent_promoted",
    }
    return fields, metrics


def _has_metric_value(x: dict) -> bool:
    for key in ("percentage_change", "absolute_change", "baseline_value", "post_value"):
        v = x.get(key)
        if v not in (None, "", 0, "0"):
            return True
    return False


def _metric_row(x: dict) -> dict:
    pct = x.get("percentage_change")
    if pct is None and "percent" in x:
        pct = x.get("percent")
    if pct is None and x.get("baseline_value") and x.get("post_value") is not None:
        try:
            base, post = float(x["baseline_value"]), float(x["post_value"])
            if base:
                pct = round(100.0 * (post - base) / base, 4)
        except (TypeError, ValueError):
            pass
    return {
        "metric_name": str(x.get("metric_name") or x.get("category") or x.get("name") or "Metric")[:120],
        "category": str(x.get("metric_category") or x.get("category") or "outcome")[:60],
        "baseline_value": x.get("baseline_value"),
        "post_value": x.get("post_value"),
        "absolute_change": x.get("absolute_change"),
        "percentage_change": pct,
        "unit": str(x.get("unit") or "")[:40],
        "reported_text": str(x.get("source_passage") or x.get("reported_text") or "")[:400],
        "value_type": x.get("value_type", "reported"),
    }


def _metrics_rows(value) -> list:
    """Coerce a focused extraction ``outcomes`` block into metric-row dicts.

    Handles a single dict, a list, or dicts whose values nest arrays of metric
    dicts (a common LLM output pattern). Duplicates are removed.
    """
    items = value if isinstance(value, list) else [value]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if _has_metric_value(it):
            out.append(_metric_row(it))
        for v in it.values():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                for x in v:
                    if _has_metric_value(x):
                        out.append(_metric_row(x))
    seen = set()
    uniq = []
    for m in out:
        k = (m["metric_name"], m.get("percentage_change"), m.get("absolute_change"))
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    return uniq


def _merge_metrics(existing: list, added: list) -> list:
    """Merge recovered metrics into the existing metric list for preview."""
    merged = list(existing)
    seen = {(m.get("metric_name"), m.get("percentage_change"), m.get("absolute_change")) for m in merged}
    for m in added:
        k = (m.get("metric_name"), m.get("percentage_change"), m.get("absolute_change"))
        if k not in seen:
            merged.append(m)
            seen.add(k)
    return merged


def _baseline_fields(value, text: str) -> dict:
    v = (value or "").strip()
    if v:
        return {"has_baseline": True, "problem_baseline_description": v[:800]}
    return {}


def _timeframe_fields(value, text: str) -> dict:
    if isinstance(value, dict):
        try:
            num = float(value.get("value"))
        except (TypeError, ValueError):
            num = None
        provided_unit = str(value.get("unit") or "").strip() or ""
        if num is not None:
            unit = provided_unit or "months"
            return {
                "intervention_measurement_period_value": num,
                "intervention_measurement_period_unit": unit[:40],
            }
        # Non-numeric value (e.g. "within weeks", "late 2024"). Honour the
        # period's presence in the source without fabricating a precise number:
        # use the model-provided unit (or one parsed from text), value = 1.
        raw = str(value.get("value") or "").strip()
        unit = provided_unit if _unit_from_text(provided_unit) else _unit_from_text(raw)
        if unit:
            return {
                "intervention_measurement_period_value": 1,
                "intervention_measurement_period_unit": unit[:40],
            }
        return {}
    if isinstance(value, (int, float)):
        return {
            "intervention_measurement_period_value": value,
            "intervention_measurement_period_unit": "months",
        }
    if isinstance(value, str):
        s = value.strip()
        num = _first_number(s)
        if num is not None:
            return {
                "intervention_measurement_period_value": num,
                "intervention_measurement_period_unit": _unit_from_text(s) or "months",
            }
        unit = _unit_from_text(s)
        if unit:
            return {
                "intervention_measurement_period_value": 1,
                "intervention_measurement_period_unit": unit,
            }
    return {}


def _unit_from_text(value: str) -> str:
    lower = (value or "").lower()
    for u in ("years", "year", "quarters", "quarter", "months", "month",
              "weeks", "week", "days", "day"):
        if u in lower:
            return u[:-1] if u in ("years", "months", "weeks", "days") else u
    return ""


def _sample_fields(value, text: str) -> dict:
    n = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
    elif isinstance(value, str):
        m = _first_number(value)
        if m is not None:
            n = m
    if n is not None and n > 1:
        return {"sample_size": n}
    return {}


def _first_number(value: str):
    m = re.search(r"(\d[\d,]*\.?\d*)", value or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# ── DB loading ───────────────────────────────────────────────────────────

GOLD_COLUMNS = (
    "id", "organization_name", "organization_anonymized", "result_status",
    "has_baseline", "problem_baseline_description", "intervention_measurement_period_value",
    "intervention_measurement_period_unit", "sample_size", "independently_verified",
    "vendor_reported", "source_id", "document_id", "implementation_provenance",
    "outcome_provenance", "implementation_richness", "evidence_level",
    "intervention_title", "organization_industry", "problem_business_function",
    "intervention_components", "outcome_block",
)


def load_records(db_path: str, tier: Optional[str] = None, limit: Optional[int] = None) -> list:
    """Load full records (all gold-card columns + their metrics) from the
    collector DB. Defensive against schema drift — columns that don't exist are
    omitted rather than erroring."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("SELECT COUNT(*) FROM intervention_records")
        except sqlite3.Error:
            return []
        present = {r[1] for r in conn.execute("PRAGMA table_info(intervention_records)")}
        cols = [c for c in GOLD_COLUMNS if c in present]
        if "id" not in cols:
            return []

        sql = f"SELECT {', '.join(cols)} FROM intervention_records"
        params: list = []
        if tier:
            sql += " WHERE evidence_level = ?"
            params.append(tier)
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        records = []
        for r in rows:
            rec = dict(r)
            for key in ("intervention_components", "outcome_block", "organization_industry", "problem_business_function"):
                if isinstance(rec.get(key), str):
                    try:
                        rec[key] = json.loads(rec[key])
                    except Exception:
                        rec[key] = []
            rec["metrics"] = _load_metrics(conn, rec["id"])
            records.append(rec)
        return records
    finally:
        conn.close()


def load_records_from_engine(api_url: str = "", token: str = "", tier: str = "", limit: int = 500) -> list:
    """Load records from the live engine ``GET /api/evidence/records`` endpoint.

    Returns the same record shape as ``load_records`` (gold-card columns +
    ``metrics``) so audit/plan work identically against the engine's live DB.
    """
    import httpx

    if not api_url or not token:
        return []
    try:
        resp = httpx.get(
            f"{api_url.rstrip('/')}/api/evidence/records",
            params={"limit": min(int(limit) or 500, 1000), "tier": tier or ""},
            headers={"X-Compass-Agent-Key": token},
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("records") or []
    except Exception as exc:
        log.warning("load_records_from_engine failed: %s", exc)
        return []


def _load_metrics(conn, intervention_id: str) -> list:
    try:
        rows = conn.execute(
            "SELECT metric_name, metric_category, baseline_value, post_value,"
            " absolute_change, percentage_change, unit, reported_text"
            " FROM metric_records WHERE intervention_id = ?",
            (intervention_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


# ── Apply (opt-in) ───────────────────────────────────────────────────────

def apply_promotions(
    promotions: list,
    records_by_id: dict,
    settings,
    budget,
    max_applications: int = 5,
    concurrency: int = 1,
) -> dict:
    """Re-extract the missing components for the top ``max_applications``
    promotions and sync them to the engine.

    Requires an LLM API key + sync token. Budget-gated per application. Returns
    a summary dict with per-record outcomes. Pure dry-run when no LLM/token.
    """
    from compass_agent.llm import LLMClient

    if not settings.provider_api_key_configured:
        log.warning("apply_promotions skipped: no provider API key configured.")
        return {"applied": 0, "promoted": 0, "skipped": max_applications, "reason": "no_api_key"}

    import httpx

    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=max(1, concurrency),
    )
    applied = 0
    promoted = 0
    failed = []
    out: list[dict] = []

    for promo in promotions[:max_applications]:
        if budget is not None and not budget.can_work():
            failed.append({"record_id": promo.record_id, "reason": "budget"})
            break
        record = records_by_id.get(promo.record_id)
        if not record or not promo.fillable_missing:
            failed.append({"record_id": promo.record_id, "reason": "no_fillable_missing"})
            continue

        text = _fetch_source(record)
        if len((text or "").strip()) < 80:
            failed.append({"record_id": promo.record_id, "reason": "no_source_text"})
            continue

        try:
            result = llm.enrich_focused(
                text,
                system=promotion_system_prompt(promo),
                user=promotion_prompt(record, promo),
                title=record.get("intervention_title", ""),
                url=record.get("source_id", ""),
            )
        except Exception as exc:
            failed.append({"record_id": promo.record_id, "reason": f"llm_error: {exc}"})
            continue

        if budget is not None and result.cost > 0:
            budget.spend(result.cost)

        extraction = result.payload if isinstance(result.payload, dict) else {}
        fields, metrics = promotion_fields(record, promo, extraction)
        if not fields and not metrics:
            failed.append({"record_id": promo.record_id, "reason": "no_fields_recovered"})
            continue

        status, resp = _post_enrichment(settings, promo.record_id, fields, metrics=metrics)
        if status == 200:
            applied += 1
            level = ""
            try:
                level = resp.get("evidence_level") if isinstance(resp, dict) else ""
            except Exception:
                level = ""
            if level == "gold":
                promoted += 1
            out.append(
                {
                    "record_id": promo.record_id,
                    "applied_fields": sorted(fields.keys()),
                    "metrics_added": len(metrics),
                    "evidence_level": level,
                }
            )
        else:
            failed.append({"record_id": promo.record_id, "reason": f"http_{status}: {resp}"})

    summary = {
        "applied": applied,
        "promoted_to_gold": promoted,
        "failed": len(failed),
        "failures": failed[:10],
        "details": out,
    }
    if budget is not None:
        summary["daily_spent"] = round(budget.daily_spent, 6)
    return summary


def promotion_system_prompt(promo: Promotion) -> str:
    return PROMOTION_SYSTEM_PROMPT + (
        f" Target tier: gold. Missing components to attempt: "
        f"{', '.join(promo.fillable_missing) or 'none'}."
    )


def _fetch_source(record: dict) -> str:
    """Fetch the source document text via the shared HttpFetcher.

    Falls back to the persisted ``intervention_components.source_url`` when
    ``source_id`` is not a URL (discovered records store the URL there)."""
    from compass_agent.discovery import HttpFetcher

    url = record.get("source_id") or ""
    if not url.startswith(("http://", "https://")):
        comps = record.get("intervention_components") or {}
        url = comps.get("source_url") if isinstance(comps, dict) else ""
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        return HttpFetcher().fetch(url, record.get("intervention_title", ""))
    except Exception as exc:
        log.warning("source fetch failed for %s: %s", url, exc)
        return ""


def _post_enrichment(settings, record_id: str, fields: dict, metrics: Optional[list] = None):
    import httpx

    try:
        resp = httpx.post(
            f"{settings.compass_api_url.rstrip('/')}/api/evidence/enrichment",
            headers={"X-Compass-Agent-Key": settings.sync_token},
            json={
                "record_id": record_id,
                "fields": fields,
                "source": "compass_agent:promote",
                "metrics": metrics or [],
                "reclassify": True,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, resp.text[:200]
        return resp.status_code, resp.text[:200]
    except Exception as exc:
        return 0, str(exc)


__all__ = [
    "compute_points",
    "classify_tier",
    "audit_bronze",
    "plan_promotions",
    "load_records",
    "apply_promotions",
    "promotion_prompt",
    "promotion_fields",
    "bronze_reasons",
    "primary_bronze_reason",
    "BronzeAudit",
    "Promotion",
    "BRONZE_REASON_LABELS",
]
