"""Backfill: normalize existing evidence records onto the canonical taxonomy.

Phase 3. For every record the backfill computes a normalized organization
payload that preserves, per field: raw value, normalized value, source,
explicit|inferred, confidence, and normalization version. Raw values are never
overwritten — normalized values are stored alongside in
``intervention_records.organization_normalized`` (JSON).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from compass_collector.organization.taxonomy import (
    NORMALIZATION_VERSION,
    normalize_employee_count,
    normalize_geography,
    normalize_industry,
    normalize_operational_function,
    regulatory_intensity_for,
)

_GEO_PATTERNS = [
    (r"\b(?:based|headquartered|headquarters) in ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", 0.8),
    (r"\b(U\.S\.|USA|United States|UK|Germany|Canada|Japan|Australia|India|China|Singapore|Brazil|Netherlands|Sweden|Switzerland|France|Spain|Italy)\b", 0.7),
]
_COUNTRY_MAP = {
    "us": "United States", "usa": "United States", "u.s.": "United States",
    "united states": "United States", "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
}

_EMP_PATTERNS = [
    r"(\d[\d,]*)\s*(?:employees|people|staff|ftes|employees worldwide)",
    r"(?:more than|over|>|~|around)\s*(\d[\d,]*)\s*employees",
]


def extract_geography(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, conf in _GEO_PATTERNS:
        m = re.search(pattern, text)
        if m:
            candidate = m.group(1).strip()
            key = candidate.lower()
            return _COUNTRY_MAP.get(key, candidate)
    return None


def extract_employee_count(text: str) -> Optional[int]:
    if not text:
        return None
    for pattern in _EMP_PATTERNS:
        m = re.search(pattern, text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def normalize_record(record: Any) -> dict:
    """Compute the normalized organization payload for one intervention record.

    Returns ``{field: {raw, value, source, method, confidence, version}, ...}``.
    """
    result: dict[str, Any] = {}
    raw_industry = record.organization_industry or []
    if isinstance(raw_industry, str):
        try:
            raw_industry = json.loads(raw_industry)
        except (json.JSONDecodeError, TypeError):
            raw_industry = [raw_industry]

    industry_norms = [normalize_industry(str(i)) for i in raw_industry]
    mapped = [n for n in industry_norms if n.mapped]
    primary = mapped[0] if mapped else None

    # Company name (cleaned canonical, raw preserved)
    from compass_collector.organization.profile import clean_company_name

    if record.organization_name:
        result["canonical_name"] = {
            "raw": record.organization_name,
            "value": clean_company_name(record.organization_name),
            "source": "backfill",
            "method": "explicit",
            "confidence": 1.0,
            "version": NORMALIZATION_VERSION,
        }

    # Industry: normalize to canonical + subsector + broader group
    if primary:
        result["primary_industry"] = {
            "raw": primary.raw,
            "value": primary.canonical,
            "source": "taxonomy",
            "method": "explicit" if primary.confidence >= 1.0 else "inferred",
            "confidence": primary.confidence,
            "version": NORMALIZATION_VERSION,
            "subsector": primary.subsector,
            "broader": primary.broader,
        }
        reg = regulatory_intensity_for(primary.canonical)
        if reg:
            result["regulatory_context"] = {
                "raw": primary.raw,
                "value": reg,
                "source": "taxonomy",
                "method": "inferred",
                "confidence": 0.6,
                "version": NORMALIZATION_VERSION,
            }

    # Employee count / band from structured field or text inference
    emp = record.organization_employee_count
    if emp is None and record.problem_statement:
        emp = extract_employee_count(record.problem_statement)
    if emp is not None:
        nv = normalize_employee_count(emp)
        result["employee_count"] = {
            "raw": str(emp),
            "value": nv.value,
            "source": "structured" if record.organization_employee_count is not None else "text_inference",
            "method": "explicit" if record.organization_employee_count is not None else "inferred",
            "confidence": 1.0 if record.organization_employee_count is not None else 0.4,
            "version": NORMALIZATION_VERSION,
        }

    # Geography from structured field or text inference
    geo = None
    if record.organization_geography:
        geo_list = record.organization_geography if isinstance(record.organization_geography, list) else [record.organization_geography]
        geo = next((g for g in geo_list if g), None)
    if geo is None and record.problem_statement:
        geo = extract_geography(record.problem_statement)
    if geo:
        nv = normalize_geography(geo)
        result["geography"] = {
            "raw": geo,
            "value": nv.value,
            "source": "structured" if record.organization_geography else "text_inference",
            "method": "explicit" if record.organization_geography else "inferred",
            "confidence": nv.confidence if record.organization_geography else 0.5,
            "version": NORMALIZATION_VERSION,
        }

    # Operational function
    bf = record.problem_business_function or []
    if bf:
        first = bf[0] if isinstance(bf, list) else bf
        nv = normalize_operational_function(first)
        result["operational_function"] = {
            "raw": str(first),
            "value": nv.value,
            "source": "backfill",
            "method": nv.method,
            "confidence": nv.confidence,
            "version": NORMALIZATION_VERSION,
        }

    result["_meta"] = {
        "record_id": record.id,
        "normalization_version": NORMALIZATION_VERSION,
        "normalized_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


# ---------------------------------------------------------------------------
# Phase 4 — vendor & technology canonicalization (canonical knowledge layer)
# ---------------------------------------------------------------------------


def _as_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v and str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if v and str(v).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        return [value.strip()]
    return []


def normalize_vendors_software(record: Any) -> dict:
    """Compute the canonical vendor/technology payload for one record.

    Returns ``{"vendors": {raw: {...}}, "software": {raw: {...}}}`` where each
    entry preserves raw, canonical value, label, method, confidence, version.
    Raw values are never overwritten — normalized values go in
    ``intervention_vendors_normalized`` / ``intervention_software_normalized``.
    """
    from compass_collector.organization.vendor_taxonomy import (
        VENDOR_NORMALIZATION_VERSION,
        normalize_vendor,
        normalize_technology,
        technology_family,
        technology_label,
        vendor_label,
    )

    payload: dict[str, dict] = {"vendors": {}, "software": {}}

    for raw in _as_list(record.intervention_vendors):
        nv = normalize_vendor(raw)
        entry = {
            "raw": raw,
            "value": nv.value,
            "source": nv.source,
            "method": nv.method,
            "confidence": round(nv.confidence, 3),
            "version": nv.version,
        }
        label = vendor_label(nv.value)
        if label:
            entry["label"] = label
        payload["vendors"][raw] = entry

    for raw in _as_list(record.intervention_software):
        nv = normalize_technology(raw)
        entry = {
            "raw": raw,
            "value": nv.value,
            "source": nv.source,
            "method": nv.method,
            "confidence": round(nv.confidence, 3),
            "version": nv.version,
        }
        label = technology_label(nv.value)
        if label:
            entry["label"] = label
        family = technology_family(nv.value)
        if family:
            entry["family"] = family
        payload["software"][raw] = entry

    return payload


def run_vendor_technology_backfill(session, dry_run: bool = True, limit: Optional[int] = None) -> dict:
    """Normalize vendors + technologies on all intervention records.

    Writes ``intervention_vendors_normalized`` and
    ``intervention_software_normalized`` when ``dry_run=False``. Raw values are
    preserved in the original columns. Reports mapping coverage and the
    unmapped long tail so the taxonomy can be extended iteratively.
    """
    from compass_collector.models.intervention import InterventionRecord

    query = session.query(InterventionRecord)
    if limit:
        query = query.limit(limit)
    records = query.all()

    vendor_raw_total = 0
    vendor_mapped = 0
    tech_raw_total = 0
    tech_mapped = 0
    records_with_vendors = 0
    records_with_tech = 0
    canonical_vendors: Counter = Counter()
    canonical_tech: Counter = Counter()
    tech_families: Counter = Counter()
    unmapped_vendors: Counter = Counter()
    unmapped_tech: Counter = Counter()
    written = 0

    for rec in records:
        payload = normalize_vendors_software(rec)
        vp, sp = payload["vendors"], payload["software"]
        if vp:
            records_with_vendors += 1
        if sp:
            records_with_tech += 1
        for raw, entry in vp.items():
            vendor_raw_total += 1
            if entry["confidence"] >= 0.7:
                vendor_mapped += 1
                canonical_vendors[entry["value"]] += 1
            else:
                unmapped_vendors[raw] += 1
        for raw, entry in sp.items():
            tech_raw_total += 1
            if entry["confidence"] >= 0.7:
                tech_mapped += 1
                canonical_tech[entry["value"]] += 1
                if entry.get("family"):
                    tech_families[entry["family"]] += 1
            else:
                unmapped_tech[raw] += 1

        if not dry_run:
            rec.intervention_vendors_normalized = vp or {}
            rec.intervention_software_normalized = sp or {}
            written += 1

    if not dry_run:
        session.commit()

    return {
        "dry_run": dry_run,
        "total_records": len(records),
        "written": written,
        "vendor": {
            "records_with_vendors": records_with_vendors,
            "raw_values": vendor_raw_total,
            "mapped": vendor_mapped,
            "mapped_pct": round(100 * vendor_mapped / max(vendor_raw_total, 1), 1),
            "distinct_raw": len(unmapped_vendors) + len(canonical_vendors),
            "distinct_canonical": len(canonical_vendors),
            "top_canonical": canonical_vendors.most_common(20),
            "unmapped_count": len(unmapped_vendors),
            "unmapped_top": unmapped_vendors.most_common(30),
        },
        "technology": {
            "records_with_software": records_with_tech,
            "raw_values": tech_raw_total,
            "mapped": tech_mapped,
            "mapped_pct": round(100 * tech_mapped / max(tech_raw_total, 1), 1),
            "distinct_raw": len(unmapped_tech) + len(canonical_tech),
            "distinct_canonical": len(canonical_tech),
            "top_canonical": canonical_tech.most_common(20),
            "families": tech_families.most_common(20),
            "unmapped_count": len(unmapped_tech),
            "unmapped_top": unmapped_tech.most_common(30),
        },
    }


def run_backfill(session, dry_run: bool = True, limit: Optional[int] = None) -> dict:
    """Normalize all intervention records. Writes when ``dry_run=False``.

    Scale-hardened: idempotent (records already normalized at the current
    ``NORMALIZATION_VERSION`` are skipped), commits in batches to keep
    transactions short, and reports extraction gains (geography/employee count
    recovered from free text) plus the unmapped industry long tail.
    """
    from compass_collector.models.intervention import InterventionRecord

    query = session.query(InterventionRecord)
    if limit:
        query = query.limit(limit)
    records = query.all()

    coverage: dict[str, Counter] = {}
    unmapped_industries: Counter = Counter()
    written = 0
    skipped = 0
    batch_size = 200
    for i, rec in enumerate(records):
        existing = rec.organization_normalized or {}
        meta = existing.get("_meta") or {}
        if meta.get("normalization_version") == NORMALIZATION_VERSION:
            skipped += 1
            continue
        payload = normalize_record(rec)
        for field in ("canonical_name", "primary_industry", "employee_count", "geography", "operational_function", "regulatory_context"):
            coverage.setdefault(field, Counter())
            coverage[field]["present"] += 1 if payload.get(field) else 0
            coverage[field]["total"] += 1
        if payload.get("primary_industry"):
            coverage["primary_industry"]["mapped"] += 1
        else:
            for raw in (rec.organization_industry or []):
                unmapped_industries[str(raw)] += 1

        if not dry_run:
            rec.organization_normalized = payload
            written += 1
            if written % batch_size == 0:
                session.commit()  # keep transactions short on large graphs

    if not dry_run:
        session.commit()

    report = {
        "dry_run": dry_run,
        "total_records": len(records),
        "written": written,
        "skipped_already_normalized": skipped,
        "field_coverage": {
            field: {
                "present": c["present"],
                "total": c["total"],
                "pct": round(100 * c["present"] / max(c["total"], 1), 1),
            }
            for field, c in coverage.items()
        },
        "unmapped_industry_count": len(unmapped_industries),
        "unmapped_industries_top": unmapped_industries.most_common(30),
        "normalization_version": NORMALIZATION_VERSION,
    }
    return report
