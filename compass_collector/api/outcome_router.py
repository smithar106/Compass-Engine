"""Outcome feedback endpoints.

Customers record what happened after acting on a recommendation. This becomes
the internal evidence moat: realized results, blueprint adherence, cost,
duration, constraints, and whether Compass would make the same call again.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from compass_collector.database import get_session
from compass_collector.models.outcome import DecisionOutcome

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


class OutcomeRequest(BaseModel):
    recommendation_id: str
    organization_name: str = ""
    accepted: Optional[bool] = None
    implemented_intervention: str = ""
    blueprint_followed: Optional[bool] = None
    realized_cost: Optional[float] = None
    implementation_duration: str = ""
    measured_result: str = ""
    unexpected_constraints: str = ""
    would_recommend_same: Optional[bool] = None


@router.post("")
def record_outcome(req: OutcomeRequest):
    if not req.recommendation_id:
        raise HTTPException(status_code=400, detail="recommendation_id required")
    db = get_session()
    try:
        rec = DecisionOutcome(
            id=str(uuid.uuid4()),
            recommendation_id=req.recommendation_id,
            organization_name=(req.organization_name or "").strip(),
            accepted=req.accepted,
            implemented_intervention=(req.implemented_intervention or "").strip(),
            blueprint_followed=req.blueprint_followed,
            realized_cost=req.realized_cost,
            implementation_duration=(req.implementation_duration or "").strip(),
            measured_result=(req.measured_result or "").strip(),
            unexpected_constraints=(req.unexpected_constraints or "").strip(),
            would_recommend_same=req.would_recommend_same,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec)
        db.commit()
        return {"outcome_id": rec.id, "status": "recorded"}
    finally:
        db.close()


@router.get("")
def list_outcomes(limit: int = 50):
    db = get_session()
    try:
        rows = (
            db.query(DecisionOutcome)
            .order_by(DecisionOutcome.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "total": len(rows),
            "outcomes": [
                {
                    "id": r.id,
                    "recommendation_id": r.recommendation_id,
                    "organization_name": r.organization_name,
                    "accepted": r.accepted,
                    "implemented_intervention": r.implemented_intervention,
                    "blueprint_followed": r.blueprint_followed,
                    "realized_cost": r.realized_cost,
                    "implementation_duration": r.implementation_duration,
                    "measured_result": r.measured_result,
                    "unexpected_constraints": r.unexpected_constraints,
                    "would_recommend_same": r.would_recommend_same,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
        }
    finally:
        db.close()
