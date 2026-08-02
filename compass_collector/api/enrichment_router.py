"""Enrichment ingestion endpoint (Phase 5 sync).

The Compass Evidence Agent publishes validated LLM enrichment back into the
engine's evidence database over HTTP. This endpoint upserts those fields onto
the matching intervention record.

Authentication: the engine reads ``AGENT_SYNC_TOKEN`` and requires the agent to
send it in the ``X-Compass-Agent-Key`` header. When the token is unset the
endpoint refuses all writes (safe default).
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


class EnrichmentRequest(BaseModel):
    record_id: str
    fields: dict = Field(default_factory=dict)
    source: str = "compass_agent"


def _authorized(request: Request) -> bool:
    token = os.environ.get("AGENT_SYNC_TOKEN", "")
    if not token:
        return False
    provided = request.headers.get("X-Compass-Agent-Key", "")
    return bool(provided) and hmac.compare_digest(provided, token)


def _apply_field(rec: InterventionRecord, column: str, value: Any) -> None:
    """Set a column on the record if it exists on the model."""
    if not hasattr(rec, column):
        raise ValueError(f"unknown column: {column}")
    if isinstance(value, str) and value == "":
        return  # do not blank existing values with empty strings
    setattr(rec, column, value)


@router.post("/enrichment")
def ingest_enrichment(req: EnrichmentRequest, request: Request):
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    if not req.record_id:
        raise HTTPException(status_code=400, detail="record_id required")
    if not req.fields:
        raise HTTPException(status_code=400, detail="fields required")

    db = get_session()
    try:
        rec = db.query(InterventionRecord).filter_by(id=req.record_id).first()
        if not rec:
            raise HTTPException(status_code=404, detail="record not found")

        applied = []
        try:
            for column, value in req.fields.items():
                _apply_field(rec, column, value)
                applied.append(column)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc))

        if not rec.intervention_components or not isinstance(rec.intervention_components, dict):
            rec.intervention_components = {}
        rec.intervention_components.setdefault("source_generation", "agent_enriched")
        db.commit()
        return {"record_id": req.record_id, "updated": len(applied), "fields": applied}
    finally:
        db.close()


@router.get("/coverage")
def evidence_coverage():
    """Per-field organization coverage across the evidence graph.

    Used to benchmark the organization/industry matching upgrade and to track
    how enrichment is closing the sparse-field gaps (employee size, geography,
    operational function, workflow).
    """
    from collections import Counter

    db = get_session()
    try:
        records = db.query(InterventionRecord).all()
    finally:
        db.close()

    total = len(records)

    def _has(value) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, list) and not value:
            return False
        if isinstance(value, dict) and not value:
            return False
        return True

    industry_raw = Counter()
    canonical_industry = Counter()
    subsector = Counter()
    agent_enriched = 0
    name = emp = emp_band = geo = op_func = workflow = normalized = 0

    for rec in records:
        if _has(rec.organization_name):
            name += 1
        if rec.organization_industry:
            for ind in rec.organization_industry:
                if ind:
                    industry_raw[str(ind)] += 1
        norm = rec.organization_normalized or {}
        if norm:
            normalized += 1
            pi = (norm.get("primary_industry") or {}).get("value")
            if pi:
                canonical_industry[pi] += 1
            sub = (norm.get("primary_industry") or {}).get("subsector")
            if sub:
                subsector[sub] += 1
        if _has(rec.organization_employee_count):
            emp += 1
        if _has(rec.organization_employee_band):
            emp_band += 1
        if _has(rec.organization_geography):
            geo += 1
        if _has(rec.problem_business_function):
            op_func += 1
        comps = rec.intervention_components or {}
        if isinstance(comps, dict) and _has(comps.get("workflow")):
            workflow += 1
        if rec.review_status == "agent_enriched" or (
            isinstance(comps, dict) and comps.get("source_generation") == "agent_enriched"
        ):
            agent_enriched += 1

    def pct(n: int) -> float:
        return round(100 * n / max(total, 1), 1)

    return {
        "total_records": total,
        "coverage": {
            "organization_name": {"n": name, "pct": pct(name)},
            "normalized_org": {"n": normalized, "pct": pct(normalized)},
            "industry_raw_unique": len(industry_raw),
            "canonical_industry": {"n": sum(canonical_industry.values()), "pct": pct(sum(canonical_industry.values()))},
            "industry_subsector": {"n": sum(subsector.values()), "pct": pct(sum(subsector.values()))},
            "employee_count": {"n": emp, "pct": pct(emp)},
            "employee_band": {"n": emp_band, "pct": pct(emp_band)},
            "geography": {"n": geo, "pct": pct(geo)},
            "operational_function": {"n": op_func, "pct": pct(op_func)},
            "workflow": {"n": workflow, "pct": pct(workflow)},
        },
        "agent_enriched_records": agent_enriched,
        "canonical_industry_top": canonical_industry.most_common(20),
        "subsector_top": subsector.most_common(20),
    }
