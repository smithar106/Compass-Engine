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
