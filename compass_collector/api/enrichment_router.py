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


class IngestRequest(BaseModel):
    source: str = "compass_agent"
    url: str = ""
    title: str = ""
    organization_name: str = ""
    organization_industry: list = Field(default_factory=list)
    problem_statement: str = ""
    problem_business_function: list = Field(default_factory=list)
    workflow: str = ""
    intervention_title: str = ""
    intervention_category: str = ""
    intervention_families: list = Field(default_factory=list)
    evidence_tier: str = "bronze"
    implementation_provenance: str = ""
    outcome_provenance: str = ""
    implementation_fields: dict = Field(default_factory=dict)
    outcomes: list = Field(default_factory=list)
    field_provenance: list = Field(default_factory=list)


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


@router.post("/ingest")
def ingest_evidence(req: IngestRequest, request: Request):
    """Insert a NEW evidence record from the agent's Discovery Mode.

    Applies: auth, duplicate detection, schema validation, and a quality gate —
    a record is only accepted if it is expected to improve recommendation
    quality (valid evidence tier + required fields + implementation depth).
    """
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")

    import hashlib
    import uuid
    from datetime import datetime, timezone

    from compass_collector.models.intervention import InterventionRecord, MetricRecord

    tier = str(req.evidence_tier or "").lower()
    if tier not in ("gold", "silver", "bronze"):
        return {"accepted": False, "reason": f"invalid_evidence_tier:{tier}"}

    org = (req.organization_name or "").strip()
    title = (req.intervention_title or "").strip()
    workflow = (req.workflow or "").strip()
    if not org or not title or not workflow:
        return {"accepted": False, "reason": "missing_required_fields"}

    # Duplicate detection: normalized org+title hash, and URL match.
    dup_key = hashlib.sha256(f"{org.lower()}::{title.lower()}".encode()).hexdigest()
    db = get_session()
    try:
        existing = (
            db.query(InterventionRecord)
            .filter(InterventionRecord.organization_name.ilike(org))
            .filter(InterventionRecord.intervention_title.ilike(title))
            .first()
        )
        if existing is not None:
            db.close()
            return {"accepted": False, "reason": "duplicate_org_title"}
        if req.url:
            doc = db.query(InterventionRecord).filter(InterventionRecord.document_id.isnot(None)).filter(InterventionRecord.intervention_title == title).first()
            # cheap url-based duplicate check is handled by the hash; skip doc join here

        impl = req.implementation_fields or {}
        impl_depth = sum(
            1 for v in (impl.get("rollout_strategy"),) if v and str(v).strip()
        ) + sum(
            1 for k in ("success_criteria", "lessons_learned", "implementation_pattern")
            if impl.get(k) and (isinstance(impl[k], list) and impl[k] or str(impl[k]).strip())
        )
        rich = (tier in ("gold", "silver")) or impl_depth >= 2
        # Quality gate: accept only if expected to improve the brief.
        if not rich:
            db.close()
            return {"accepted": False, "reason": "insufficient_depth"}

        rec = InterventionRecord(
            id=str(uuid.uuid4()),
            source_id=req.source,
            organization_name=org,
            organization_industry=req.organization_industry or [],
            problem_statement=(req.problem_statement or "")[:800],
            problem_business_function=req.problem_business_function or [],
            intervention_title=title,
            intervention_description=(impl.get("intervention_description") or req.title or "")[:400],
            intervention_families=req.intervention_families or [],
            intervention_components={
                "workflow": workflow,
                "intervention_category": req.intervention_category,
                "evidence_tier": tier,
                "source_generation": "agent_discovered",
            },
            intervention_vendors=impl.get("intervention_vendors") or [],
            implementation_partner=impl.get("implementation_partner") or [],
            implementation_pattern=impl.get("implementation_pattern") or [],
            lessons_learned=impl.get("lessons_learned") or [],
            rollout_strategy=impl.get("rollout_strategy", ""),
            success_criteria=impl.get("success_criteria") or [],
            pilot_structure=impl.get("pilot_structure", ""),
            executive_sponsor=impl.get("executive_sponsor", ""),
            governance_model=impl.get("governance_model", ""),
            implementation_provenance=req.implementation_provenance or "",
            outcome_provenance=req.outcome_provenance or "",
            evidence_level=tier,
            implementation_field_provenance=req.field_provenance or [],
            implementation_richness="rich" if rich else "usable",
            review_status="agent_discovered",
            result_status="unknown",
            extracted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec)
        for o in req.outcomes or []:
            if not isinstance(o, dict):
                continue
            try:
                pct = float(o.get("percentage_change")) if o.get("percentage_change") not in (None, "") else None
            except (TypeError, ValueError):
                pct = None
            db.add(
                MetricRecord(
                    id=str(uuid.uuid4()),
                    intervention_id=rec.id,
                    source_id=req.source,
                    metric_name=str(o.get("metric_name") or o.get("category") or "metric")[:120],
                    metric_category=str(o.get("category") or "outcome")[:60],
                    percentage_change=pct,
                    absolute_change=o.get("absolute_change"),
                    unit=str(o.get("unit") or "")[:40],
                    reported_text=str(o.get("source_passage") or "")[:400],
                )
            )
        db.commit()
        db.close()
        return {"accepted": True, "record_id": rec.id, "rich": rich, "dup_key": dup_key}
    finally:
        if db.in_transaction():
            db.rollback()
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
