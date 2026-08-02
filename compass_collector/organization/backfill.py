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


def run_backfill(session, dry_run: bool = True, limit: Optional[int] = None) -> dict:
    """Normalize all intervention records. Writes when ``dry_run=False``."""
    from compass_collector.models.intervention import InterventionRecord

    query = session.query(InterventionRecord)
    if limit:
        query = query.limit(limit)
    records = query.all()

    coverage: dict[str, Counter] = {}
    unmapped_industries: Counter = Counter()
    written = 0
    for rec in records:
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

    if not dry_run:
        session.commit()

    report = {
        "dry_run": dry_run,
        "total_records": len(records),
        "written": written,
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
