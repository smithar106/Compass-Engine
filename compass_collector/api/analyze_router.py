"""Server-side Analyze analysis sessions.

The engine owns the decision process: normalization, inference, adaptive
question selection, retrieval, scoring, and the final Decision Package are
all produced here and persisted as a first-class, versioned record. The
website is a thin client over these endpoints.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from compass_collector.database import get_session
from compass_collector.models.analysis_session import AnalysisSession
from compass_collector.analysis.analyze import (
    normalize_problem,
    select_follow_ups,
    infer_answers_from_text,
    build_profile_from_analyze,
)
from compass_collector.api.schemas import InvestigationRequest

logger = logging.getLogger("compass-engine.analyze")

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

ENGINE_VERSION = "3.1.0"
SCORING_VERSION = "1.0.0"


class AnalyzeCreateRequest(BaseModel):
    problem_text: str
    attachments: List[str] = Field(default_factory=list)
    organization_name: str = ""
    organization_domain: str = ""
    organization_industry: str = ""


class ConfirmRequest(BaseModel):
    edits: Dict[str, str] = Field(default_factory=dict)
    organization: Optional[Dict[str, Any]] = None


class AnswersRequest(BaseModel):
    answers: Dict[str, str] = Field(default_factory=dict)


def _new_id() -> str:
    return str(uuid.uuid4())


def _session_to_dict(session: AnalysisSession) -> Dict[str, Any]:
    return {
        "analysis_id": session.id,
        "original_input": session.original_input,
        "attachments": session.attachments or [],
        "normalization": session.normalization or {},
        "edits": session.edits or {},
        "inferred": session.inferred or [],
        "questions": session.questions or [],
        "answers": session.answers or {},
        "organization": session.organization or None,
        "evidence_ids": session.evidence_ids or [],
        "retrieval_snapshots": session.retrieval_snapshots or [],
        "status": session.status,
        "scoring_version": session.scoring_version,
        "engine_version": session.engine_version,
        "decision": session.decision,
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else "",
    }


def _load(session_id: str) -> AnalysisSession:
    db = get_session()
    try:
        row = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return row


def _save(row: AnalysisSession) -> None:
    db = get_session()
    try:
        row.updated_at = datetime.utcnow()
        db.merge(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def extract_evidence_ids(decision: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for rec in (decision or {}).get("recommendations", []):
        for c in rec.get("comparable_implementations", []):
            rid = c.get("record_id")
            if rid:
                ids.append(rid)
    return list(dict.fromkeys(ids))


def _engine_gaps(decision: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not decision:
        return []
    top = (decision.get("recommendations") or [{}])[0]
    return top.get("information_gaps") or decision.get("information_gaps") or []


def _run_engine(normalization: Dict[str, str], answers: Dict[str, str], organization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the live retrieval + scoring pipeline and return the engine result."""
    from compass_collector.api.service import run_recommendation

    profile = build_profile_from_analyze(normalization, answers)
    if organization:
        org = organization.get("proposed") or organization
        fields = org.get("fields", {}) or {}
        if not profile.get("industry"):
            profile["industry"] = fields.get("primary_industry", {}).get("value", "")
        if not profile.get("geography"):
            profile["geography"] = fields.get("headquarters_country", {}).get("value", "")
        if not profile.get("company_size"):
            profile["company_size"] = fields.get("employee_band", {}).get("value", "")
    request = InvestigationRequest(**profile)
    response = run_recommendation(request, org_profile=organization)
    return response.model_dump()


def _conf_status(decision: Optional[Dict[str, Any]]) -> str:
    """Decision-only status: ready or honestly deferred."""
    if not decision:
        return "awaiting_answers"
    top = (decision.get("recommendations") or [{}])[0]
    label = top.get("confidence", {}).get("label", "")
    tier = (top.get("evidence_summary") or {}).get("overall_tier", "")
    total = (top.get("evidence_summary") or {}).get("total_comparables", 0) or 0
    if label == "insufficient" or tier == "insufficient" or total == 0:
        return "insufficient_evidence"
    return "decision_ready"


def _run_decision(session: AnalysisSession) -> Dict[str, Any]:
    """Run live retrieval + scoring and record the evidence snapshot."""
    decision = _run_engine(
        session.normalization or {},
        session.answers or {},
        organization=session.organization,
    )
    session.decision = decision
    session.evidence_ids = extract_evidence_ids(decision)
    session.retrieval_snapshots = (session.retrieval_snapshots or []) + [
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "evidence_ids": session.evidence_ids,
            "top": ((decision.get("recommendations") or [{}])[0].get("title") if decision.get("recommendations") else ""),
        }
    ]
    session.retrieval_snapshots = session.retrieval_snapshots[-10:]
    session.scoring_version = SCORING_VERSION
    session.engine_version = ENGINE_VERSION
    _save(session)
    return decision


def _select_questions(session: AnalysisSession) -> None:
    """Select the single round of up to five targeted questions and set status."""
    session.questions = select_follow_ups(
        text=session.original_input or "",
        answers=session.answers or {},
        engine_gaps=_engine_gaps(session.decision),
        max_questions=5,
    )
    session.status = "awaiting_answers" if session.questions else _conf_status(session.decision)
    _save(session)


@router.post("")
def create_analysis(req: AnalyzeCreateRequest):
    if not req.problem_text.strip():
        raise HTTPException(status_code=400, detail="problem_text is required")

    # Phase 5: demand telemetry — what decision area is being asked about?
    try:
        from compass_collector.api.demand_telemetry import record_demand_from_text

        record_demand_from_text(req.problem_text)
    except Exception:
        pass  # telemetry must never break the analyze flow

    session = AnalysisSession(
        id=_new_id(),
        original_input=req.problem_text.strip()[:8000],
        attachments=req.attachments[:10],
        normalization=normalize_problem(req.problem_text + " ".join(req.attachments)),
        inferred=sorted(infer_answers_from_text(req.problem_text + " ".join(req.attachments))),
        status="awaiting_confirmation",
        scoring_version=SCORING_VERSION,
        engine_version=ENGINE_VERSION,
    )
    # Phase 5: resolve the organization early in the Analyze flow.
    org_name = (req.organization_name or "").strip()
    org_domain = (req.organization_domain or "").strip()
    org_industry = (req.organization_industry or "").strip()
    if org_name or org_domain or org_industry:
        from compass_collector.organization.profile import resolve_organization

        db = get_session()
        try:
            resolved = resolve_organization(
                company_name=org_name,
                company_domain=org_domain,
                industry=org_industry,
                session=db,
            )
        finally:
            db.close()
        session.organization = resolved.to_dict()

    _save(session)
    try:
        _run_decision(session)
        _select_questions(session)
        return _session_to_dict(session)
    except Exception as e:
        logger.error("Initial retrieval failed for %s: %s", session.id, e)
        session.status = "error"
        _save(session)
        raise HTTPException(status_code=502, detail="Initial retrieval failed")


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str):
    return _session_to_dict(_load(analysis_id))


@router.post("/{analysis_id}/confirm")
def confirm_analysis(analysis_id: str, req: ConfirmRequest):
    session = _load(analysis_id)
    base = session.normalization or {}
    edits = {k: (v or "").strip() for k, v in (req.edits or {}).items() if v}
    session.edits = edits
    for key in ("workflow", "businessFunction", "problemStatement", "rootCauseHypothesis", "desiredOutcome"):
        if key in edits:
            base[key] = edits[key]
    session.normalization = base
    if req.organization is not None:
        session.organization = req.organization
    session.status = "awaiting_answers"
    _save(session)
    try:
        _run_decision(session)
        _select_questions(session)
        return _session_to_dict(session)
    except Exception as e:
        logger.error("Confirm failed for %s: %s", session.id, e)
        session.status = "error"
        _save(session)
        raise HTTPException(status_code=502, detail="Analysis failed")


@router.post("/{analysis_id}/answers")
def submit_answers(analysis_id: str, req: AnswersRequest):
    session = _load(analysis_id)
    answers = dict(session.answers or {})
    answers.update({k: str(v).strip() for k, v in (req.answers or {}).items() if v})
    session.answers = answers
    _save(session)
    try:
        _run_decision(session)
        session.status = _conf_status(session.decision)
        session.questions = session.questions or []
        _save(session)
        return _session_to_dict(session)
    except Exception as e:
        logger.error("Answers failed for %s: %s", session.id, e)
        session.status = "error"
        _save(session)
        raise HTTPException(status_code=502, detail="Analysis failed")
