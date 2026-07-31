"""End-to-end walkthrough: implementation choice, partner request, six-stage
plan, permanent decision links, and partner invitations.

Persistence lives on the engine (durable SQLite). Partner data is explicit
demonstration configuration until a real partner registry exists; every partner
is labeled accordingly and can never affect intervention ranking.
"""

import json
import logging
import os
import secrets
import smtplib
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from compass_collector.database import get_session
from compass_collector.models.walkthrough import (
    ImplementationPlan,
    ImplementationRequest,
    SavedDecision,
)
from compass_collector.api.analyze_router import _load as load_analysis

logger = logging.getLogger("compass-engine.walkthrough")

router = APIRouter(tags=["walkthrough"])

# ---------------------------------------------------------------------------
# Demonstration partners — clearly labeled until a real registry exists.
# ---------------------------------------------------------------------------

DEMO_PARTNERS: List[Dict[str, Any]] = [
    {
        "id": "demo-northstar",
        "name": "Northstar Automation",
        "capability": "Workflow automation and rules-based process design",
        "why": "Strong implementation history for workflow automation and rules-based interventions.",
        "interventions": ["Workflow_Automation", "Process_Redesign", "Software"],
        "delivery_model": "Managed delivery with your internal owner",
        "indicative_timeline": "4–12 weeks typical",
        "evidence_basis": "Illustrative capability profile; no verified outcomes yet.",
        "relationship_status": "demonstration",
        "rating": 4,
    },
    {
        "id": "demo-opsbridge",
        "name": "OpsBridge Partners",
        "capability": "AI-assisted and hybrid operational interventions",
        "why": "Experience with AI-assisted and hybrid implementations, including human-review workflows.",
        "interventions": ["AI", "Hybrid", "Workflow_Automation"],
        "delivery_model": "Blended on-site and remote",
        "indicative_timeline": "6–20 weeks typical",
        "evidence_basis": "Illustrative capability profile; no verified outcomes yet.",
        "relationship_status": "demonstration",
        "rating": 3,
    },
    {
        "id": "demo-cobalt",
        "name": "Cobalt Systems Integration",
        "capability": "Enterprise software and systems integration",
        "why": "Focused on platform implementation and system integration at enterprise scope.",
        "interventions": ["Software", "Process_Redesign"],
        "delivery_model": "Enterprise SI engagement model",
        "indicative_timeline": "8–30 weeks typical",
        "evidence_basis": "Illustrative capability profile; no verified outcomes yet.",
        "relationship_status": "demonstration",
        "rating": 3,
    },
]


class ImplementRequest(BaseModel):
    path: str = "partner"  # "partner" | "internal"
    partner_id: Optional[str] = None
    contact_email: str = ""


class PartnerRequestModel(BaseModel):
    partner_id: str
    contact_name: str
    contact_email: str
    organization: str
    requested_timeline: str = ""
    notes: str = ""
    consent: bool = True


class SaveDecisionModel(BaseModel):
    email: str = ""


class AcceptModel(BaseModel):
    accept: bool = True


def _new_id() -> str:
    return str(uuid.uuid4())


def _save(row: Any) -> None:
    db = get_session()
    try:
        db.merge(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _load_plan(plan_id: str) -> ImplementationPlan:
    db = get_session()
    try:
        row = db.query(ImplementationPlan).filter(ImplementationPlan.id == plan_id).first()
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Implementation plan not found")
    return row


def _plan_to_dict(plan: ImplementationPlan) -> Dict[str, Any]:
    return {
        "implementation_id": plan.id,
        "analysis_id": plan.analysis_id,
        "decision_id": plan.decision_id,
        "selected_path": plan.selected_path,
        "partner_id": plan.partner_id,
        "partner_name": plan.partner_name,
        "status": plan.status,
        "partner_status": plan.partner_status,
        "invite_token": plan.invite_token,
        "stages": plan.stages or [],
        "created_at": plan.created_at.isoformat() if plan.created_at else "",
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else "",
    }


def recommended_partner(category: str) -> Dict[str, Any]:
    for p in DEMO_PARTNERS:
        if category in p["interventions"]:
            return p
    return DEMO_PARTNERS[0]


def _add_stage(
    stages: List[Dict[str, Any]],
    index: int,
    name: str,
    purpose: str,
    activities: List[str],
    owner: str,
    partner_role: str,
    inputs: List[str],
    milestones: List[str],
    validation_gate: str,
    evidence_required: List[str],
    target_completion: str,
    notes: str,
    indicative: bool,
    source: str,
) -> None:
    stages.append(
        {
            "index": index,
            "name": name,
            "purpose": purpose,
            "activities": activities,
            "owner": owner,
            "partner_role": partner_role,
            "inputs": inputs,
            "milestones": milestones,
            "validation_gate": validation_gate,
            "status": "not_started",
            "evidence_required": evidence_required,
            "target_completion": target_completion,
            "notes": notes,
            "indicative": indicative,
            "source": source,
        }
    )


def build_six_stage_plan(decision: Dict[str, Any], normalization: Dict[str, str], path: str, partner: Dict[str, Any]) -> List[Dict[str, Any]]:
    recs = decision.get("recommendations") or []
    top = recs[0] if recs else {}
    next_step = top.get("next_validation_step") or {}
    gaps = top.get("information_gaps") or []
    risks = top.get("risks") or []
    outcome_ranges = (top.get("outcome_ranges") or [])[:3]
    problem = normalization.get("problemStatement") or "the assessed workflow"
    intervention = top.get("title") or "the recommended intervention"
    success_criteria = next_step.get("success_criteria") or "Agreed success metric met in a bounded pilot"
    baseline_action = next_step.get("action") or "Measure a baseline for the current workflow"

    stages: List[Dict[str, Any]] = []

    # Stage 1 — Confirm baseline
    _add_stage(
        stages, 1, "Confirm baseline",
        "Establish the current state so the outcome is measured against a real starting point, not an assumption.",
        [
            "Document the current workflow end to end",
            "Measure volume, cycle time, and manual effort",
            "Record error and exception rates",
        ],
        "Operations owner",
        partner["name"] if path == "partner" else "n/a",
        [baseline_action, "Current workflow documentation", "Workflow volume data"],
        ["Baseline metrics locked", "Baseline documented and approved"],
        success_criteria,
        [g["title"] for g in gaps] or ["Current-state metrics"],
        "2–3 weeks",
        "Baseline is defined before implementation begins. Not after.",
        indicative=False,
        source="decision",
    )

    # Stage 2 — Finalize solution design
    _add_stage(
        stages, 2, "Finalize solution design",
        "Turn the recommended intervention into a scoped, owned design.",
        [
            "Define scope boundaries for the intervention",
            "Confirm systems, data, and integration points",
            "Assign ownership and dependencies; record risks",
        ],
        "Project lead",
        partner["name"] if path == "partner" else "n/a",
        [intervention, "Scope boundaries from the Decision Brief"],
        ["Design approved", "Owners assigned", "Risks recorded"],
        "Design review signed off",
        ["Scope and success criteria"],
        "2–3 weeks",
        "Generic guidance below is indicative and must be validated against your systems.",
        indicative=True,
        source="indicative",
    )

    # Stage 3 — Build and configure
    _add_stage(
        stages, 3, "Build and configure",
        "Configure the solution, prepare data, and integrate.",
        [
            "Configure workflows or platform settings",
            "Prepare data and define rules",
            "Run integration and unit testing",
        ],
        "Implementation owner",
        partner["name"] if path == "partner" else "n/a",
        ["Design document", "Access to systems and data"],
        ["Build complete", "Tests passing"],
        "Integration test pass",
        ["Test results", "Integration evidence"],
        "3–6 weeks",
        "Indicative guidance — adjust to the selected tooling and partner.",
        indicative=True,
        source="indicative",
    )

    # Stage 4 — Pilot and validate
    _add_stage(
        stages, 4, "Pilot and validate",
        "Run a bounded pilot to confirm the intervention produces the expected outcome in your context.",
        [
            "Define the pilot population and duration",
            "Run the pilot with defined success criteria",
            "Review results against the validation gate",
        ],
        "Process owner",
        partner["name"] if path == "partner" else "n/a",
        ["Pilot scope", "Success criteria", "Baseline metrics"],
        ["Pilot complete", "Results reviewed"],
        f"Validation gate: {success_criteria}",
        ["Pilot outcome data", "Observed outcome ranges"],
        "3–4 weeks",
        "Go / no-go decision is made at this gate before scaling.",
        indicative=False,
        source="decision",
    )

    # Stage 5 — Roll out and adopt
    _add_stage(
        stages, 5, "Roll out and adopt",
        "Scale the intervention with training, change management, and adoption tracking.",
        [
            "Plan the rollout sequence",
            "Deliver training and change management",
            "Track adoption and define escalation paths",
        ],
        "Operations owner",
        partner["name"] if path == "partner" else "n/a",
        ["Pilot results", "Rollout plan", "Training materials"],
        ["Rollout complete", "Adoption target reached"],
        "Adoption > 80% or agreed target",
        ["Adoption metrics"],
        "3–6 weeks",
        "Indicative guidance — tailor to your organization.",
        indicative=True,
        source="indicative",
    )

    # Stage 6 — Measure and improve
    _add_stage(
        stages, 6, "Measure and improve",
        "Review outcomes against the decision and feed the learning back into the next decision.",
        [
            "Hold 30-day, 3-month, 6-month, 9-month, and 12-month reviews",
            "Compare projected with actual outcomes",
            "Capture lessons and update the recommendation",
        ],
        "Executive sponsor",
        partner["name"] if path == "partner" else "n/a",
        [f"Expected outcomes: {json.dumps([{ 'metric': r.get('metric_label'), 'range': [r.get('low'), r.get('high')], 'unit': r.get('unit') } for r in outcome_ranges], default=str)}"],
        ["Reviews completed", "Outcomes verified", "Recommendation updated"],
        "Measured outcomes match or exceed projection",
        ["Verified outcome data"],
        "Ongoing (12-month horizon)",
        "Verified results feed back into the evidence base and the next decision.",
        indicative=False,
        source="decision",
    )

    return stages


def _send_email(to: str, subject: str, text: str) -> Dict[str, Any]:
    """Send a real email when configured; otherwise a safe development fallback."""
    mailgun_key = os.getenv("MAILGUN_API_KEY", "")
    mailgun_domain = os.getenv("MAILGUN_DOMAIN", "")
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", "compass@localhost")

    if mailgun_key and mailgun_domain:
        try:
            req = urllib.request.Request(
                f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
                data=urllib.parse.urlencode(
                    {"from": smtp_from, "to": to, "subject": subject, "text": text}
                ).encode(),
            )
            import base64
            req.add_header("Authorization", "Basic " + base64.b64encode(f"api:{mailgun_key}".encode()).decode())
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"status": "sent", "channel": "mailgun", "to": to}
        except Exception as e:
            logger.warning("Mailgun send failed: %s", e)
            return {"status": "failed", "channel": "mailgun", "error": str(e)[:200]}

    if smtp_host:
        try:
            with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to], f"Subject: {subject}\n\n{text}")
            return {"status": "sent", "channel": "smtp", "to": to}
        except Exception as e:
            logger.warning("SMTP send failed: %s", e)
            return {"status": "failed", "channel": "smtp", "error": str(e)[:200]}

    logger.info("Email not configured — dev fallback. Would email %s: %s", to, subject)
    return {
        "status": "dev_fallback",
        "channel": "dev_fallback",
        "to": to,
        "config_required": "Set MAILGUN_API_KEY + MAILGUN_DOMAIN (or SMTP_HOST) to enable email delivery.",
    }


@router.get("/api/partners")
def list_partners():
    return {"partners": DEMO_PARTNERS, "note": "Demonstration partner data. No formal relationships are implied."}


@router.post("/api/analyze/{analysis_id}/implement")
def create_implementation(analysis_id: str, req: ImplementRequest):
    analysis = load_analysis(analysis_id)
    decision = analysis.decision or {}
    normalization = analysis.normalization or {}
    recs = decision.get("recommendations") or []
    top = recs[0] if recs else {}
    category = top.get("category") or ""

    path = req.path if req.path in ("partner", "internal") else "internal"
    partner = recommended_partner(category)
    if req.partner_id:
        partner = next((p for p in DEMO_PARTNERS if p["id"] == req.partner_id), partner)

    plan = ImplementationPlan(
        id=_new_id(),
        analysis_id=analysis_id,
        decision_id=decision.get("recommendation_id") or "",
        selected_path=path,
        partner_id=partner["id"] if path == "partner" else "",
        partner_name=partner["name"] if path == "partner" else "Internal team",
        contact_email=req.contact_email,
        stages=build_six_stage_plan(decision, normalization, path, partner),
        status="active",
        partner_status="not_requested" if path == "partner" else "internal",
        invite_token=secrets.token_urlsafe(24),
        invite_expires_at=datetime.utcnow() + timedelta(days=7),
    )
    _save(plan)
    return _plan_to_dict(plan)


@router.get("/api/implementations/{impl_id}")
def get_implementation(impl_id: str):
    return _plan_to_dict(_load_plan(impl_id))


@router.post("/api/implementations/{impl_id}/request")
def request_partner(impl_id: str, req: PartnerRequestModel):
    plan = _load_plan(impl_id)
    partner = next((p for p in DEMO_PARTNERS if p["id"] == req.partner_id), None)
    if not partner:
        raise HTTPException(status_code=400, detail="Unknown partner")
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required to share the decision brief with a partner")

    request = ImplementationRequest(
        id=_new_id(),
        implementation_id=impl_id,
        partner_id=partner["id"],
        partner_name=partner["name"],
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        organization=req.organization,
        requested_timeline=req.requested_timeline,
        notes=req.notes,
        consent=req.consent,
        status="submitted",
        audit=[{"at": datetime.now(timezone.utc).isoformat(), "event": "request_created", "by": req.contact_email}],
    )

    decision = load_analysis(plan.analysis_id)
    decision_brief = decision.decision or {}
    brief_summary = (decision_brief.get("recommendations") or [{}])[0].get("title") if decision_brief.get("recommendations") else "the assessed decision"
    permalink = f"/decisions/{plan.analysis_id}"
    invite_url = f"/implementations/{impl_id}/invite/{plan.invite_token}"

    partner_email = _send_email(
        os.getenv("PARTNER_NOTIFY_EMAIL", ""),
        f"Compass introduction request — {brief_summary}",
        (
            f"{req.contact_name} ({req.contact_email}, {req.organization}) requests an introduction.\n"
            f"Decision: {brief_summary}\nPartner view: {invite_url}\n"
            f"Requested timeline: {req.requested_timeline or 'Not specified'}\nNotes: {req.notes or '—'}"
        ),
    )
    user_email = _send_email(
        req.contact_email,
        "Your Compass introduction request",
        (
            f"You requested an introduction to {partner['name']} for: {brief_summary}.\n"
            f"Review your decision at {permalink}.\n\n"
            f"Notification status: {partner_email.get('status')}."
        ),
    )

    request.status = "submitted" if partner_email.get("status") == "dev_fallback" else "notification_sent"
    request.notification = {"partner": partner_email, "user": user_email}
    request.audit.append({"at": datetime.now(timezone.utc).isoformat(), "event": "notification_attempted", "detail": partner_email})
    _save(request)

    plan.partner_status = "requested"
    plan.contact_email = req.contact_email
    plan.organization = req.organization
    _save(plan)

    return {
        "request_id": request.id,
        "implementation_id": impl_id,
        "status": request.status,
        "notification": request.notification,
        "message": "Introduction request recorded. Partner and user notifications attempted — configure email to enable delivery.",
        "permalink": permalink,
    }


@router.get("/api/implementations/{impl_id}/invite/{token}")
def partner_invite_view(impl_id: str, token: str):
    plan = _load_plan(impl_id)
    if plan.invite_token != token:
        raise HTTPException(status_code=403, detail="Invalid invite token")
    if plan.invite_expires_at and datetime.utcnow() > plan.invite_expires_at:
        raise HTTPException(status_code=410, detail="Invite has expired")

    decision = load_analysis(plan.analysis_id)
    top = ((decision.decision or {}).get("recommendations") or [{}])[0]
    return {
        "implementation_id": impl_id,
        "partner_name": plan.partner_name,
        "partner_status": plan.partner_status,
        "decision": {
            "title": top.get("title"),
            "rationale": top.get("rationale"),
            "outcome_ranges": top.get("outcome_ranges", []),
            "risks": top.get("risks", []),
            "assumptions": top.get("assumptions_detail", []),
        },
        "stages": plan.stages or [],
    }


@router.post("/api/implementations/{impl_id}/invite/{token}/accept")
def partner_invite_accept(impl_id: str, token: str, _req: AcceptModel = None):
    plan = _load_plan(impl_id)
    if plan.invite_token != token:
        raise HTTPException(status_code=403, detail="Invalid invite token")
    if plan.invite_expires_at and datetime.utcnow() > plan.invite_expires_at:
        raise HTTPException(status_code=410, detail="Invite has expired")
    plan.partner_status = "accepted"
    _save(plan)
    return {"implementation_id": impl_id, "partner_status": "accepted"}


@router.post("/api/decisions/{analysis_id}/save")
def save_decision(analysis_id: str, req: SaveDecisionModel):
    load_analysis(analysis_id)  # ensure it exists
    saved = SavedDecision(
        id=_new_id(),
        analysis_id=analysis_id,
        email=req.email,
        resume_token=secrets.token_urlsafe(24),
    )
    _save(saved)
    permalink = f"/decisions/{analysis_id}"
    if req.email:
        note = _send_email(
            req.email,
            "Your Compass decision",
            f"You saved a Compass decision. Resume it anytime: {permalink}",
        )
        saved.note = note
        _save(saved)
    else:
        note = {"status": "no_email"}
    return {"decision_id": analysis_id, "permalink": permalink, "resume_token": saved.resume_token, "notification": note}
