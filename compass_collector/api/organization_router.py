"""Organization resolution endpoints (Phase 4).

POST /api/organizations/resolve  — resolve a company name/domain/industry into
a proposed OrganizationProfile with per-field confidence, alternative matches,
and the fields that require user confirmation.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from compass_collector.database import get_session
from compass_collector.models.organization import OrganizationProfileRecord
from compass_collector.organization.profile import resolve_organization

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


class ResolveRequest(BaseModel):
    company_name: str = ""
    company_domain: str = ""
    industry: str = ""


class ConfirmRequest(BaseModel):
    company_name: str = ""
    company_domain: str = ""
    fields: dict = Field(default_factory=dict)


def _persist(profile: dict) -> str:
    db = get_session()
    try:
        rec = OrganizationProfileRecord(
            id=str(uuid.uuid4()),
            canonical_name=profile.get("canonical_name") or "",
            aliases=profile.get("aliases") or [],
            domain=profile.get("domain") or "",
            primary_industry=profile.get("primary_industry") or "",
            industry_subsector=profile.get("industry_subsector") or "",
            profile_data=profile,
        )
        db.add(rec)
        db.commit()
        return rec.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/resolve")
def resolve(req: ResolveRequest):
    name = (req.company_name or "").strip()
    domain = (req.company_domain or "").strip()
    industry = (req.industry or "").strip()
    if not (name or domain or industry):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of company_name, company_domain, or industry",
        )
    db = get_session()
    try:
        result = resolve_organization(
            company_name=name,
            company_domain=domain,
            industry=industry,
            session=db,
        )
    finally:
        db.close()
    return result.to_dict()


@router.post("/resolve/confirm")
def confirm(req: ConfirmRequest):
    """Persist a user-confirmed organization profile (for later use)."""
    if not (req.company_name or req.company_domain):
        raise HTTPException(status_code=400, detail="company_name or company_domain required")
    profile = {
        "canonical_name": (req.company_name or "").strip(),
        "domain": (req.company_domain or "").strip(),
        "aliases": [],
        "fields": req.fields or {},
        "user_confirmed": list((req.fields or {}).keys()),
    }
    record_id = _persist(profile)
    return {"organization_id": record_id, "status": "confirmed", "profile": profile}
