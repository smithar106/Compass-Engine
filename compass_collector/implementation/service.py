import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from compass_collector.database import get_session
from compass_collector.api.storage import load_recommendation, save_selection
from compass_collector.implementation.models import (
    ImplementationWorkspace, ImplementationPlanVersion, ImplementationPhase,
    ImplementationMilestone, ProgressUpdate, Blocker, DecisionRecord,
    WorkspaceDocument, SuccessMetric, CompanionMessage, ProposedPlanChange,
)

logger = logging.getLogger("compass-engine.implementation")

MILESTONE_STATUSES = ["not_started", "in_progress", "blocked", "completed", "skipped"]
BLOCKER_STATUSES = ["open", "resolved"]
PLAN_CHANGE_STATUSES = ["pending", "accepted", "rejected"]
METRIC_STATUSES = ["not_measured", "below_target", "on_track", "achieved", "regressed"]


def _phase_templates(intervention_family: str) -> list[dict]:
    templates = {
        "Workflow_Automation": [
            {"name": "Discovery & Documentation", "objective": "Map current process and identify automation opportunities", "duration": "2-3 weeks"},
            {"name": "Design & Configuration", "objective": "Design automated workflow and configure rules", "duration": "3-4 weeks"},
            {"name": "Testing & Validation", "objective": "Test automation with real data and validate outcomes", "duration": "2-3 weeks"},
            {"name": "Deployment & Monitoring", "objective": "Deploy automation, train team, establish monitoring", "duration": "2-3 weeks"},
        ],
        "AI": [
            {"name": "Assessment & Data Preparation", "objective": "Assess data availability and prepare training datasets", "duration": "3-4 weeks"},
            {"name": "Model Development & Training", "objective": "Develop and train AI model with human review", "duration": "4-6 weeks"},
            {"name": "Pilot Deployment", "objective": "Run bounded pilot with human-in-the-loop review", "duration": "3-4 weeks"},
            {"name": "Full Deployment & Monitoring", "objective": "Scale deployment, establish monitoring and retraining", "duration": "4-6 weeks"},
        ],
        "Software": [
            {"name": "Evaluation & Selection", "objective": "Evaluate platforms and select solution", "duration": "2-4 weeks"},
            {"name": "Configuration & Integration", "objective": "Configure platform and integrate with existing systems", "duration": "4-6 weeks"},
            {"name": "Migration & Testing", "objective": "Migrate data, test workflows, validate", "duration": "3-4 weeks"},
            {"name": "Go-Live & Adoption", "objective": "Launch platform, train users, drive adoption", "duration": "3-4 weeks"},
        ],
        "Process_Redesign": [
            {"name": "Current-State Analysis", "objective": "Map current processes and identify waste", "duration": "3-4 weeks"},
            {"name": "Future-State Design", "objective": "Design optimized future-state processes", "duration": "3-4 weeks"},
            {"name": "Implementation & Training", "objective": "Implement process changes and train stakeholders", "duration": "4-6 weeks"},
            {"name": "Measurement & Iteration", "objective": "Measure outcomes and iterate on improvements", "duration": "3-4 weeks"},
        ],
        "Staffing": [
            {"name": "Needs Assessment", "objective": "Assess current capacity and define role requirements", "duration": "2-3 weeks"},
            {"name": "Sourcing & Selection", "objective": "Source candidates or reassign team members", "duration": "4-6 weeks"},
            {"name": "Onboarding & Training", "objective": "Onboard new team members and provide training", "duration": "3-4 weeks"},
            {"name": "Integration & Optimization", "objective": "Integrate team into workflows and optimize", "duration": "3-4 weeks"},
        ],
    }
    return templates.get(intervention_family, [
        {"name": "Planning", "objective": "Plan implementation approach", "duration": "2-3 weeks"},
        {"name": "Execution", "objective": "Execute implementation activities", "duration": "4-6 weeks"},
        {"name": "Review", "objective": "Review outcomes and adjust", "duration": "2-3 weeks"},
    ])


def _generate_milestones(phase_name: str, phase_index: int) -> list[dict]:
    milestones_map = {
        "Discovery & Documentation": [
            "Map current-state process flow",
            "Identify automation candidates",
            "Document decision points and exceptions",
            "Stakeholder review and sign-off",
        ],
        "Design & Configuration": [
            "Design automated workflow",
            "Configure routing rules",
            "Set up exception handling",
            "Internal review and iteration",
        ],
        "Assessment & Data Preparation": [
            "Audit available data sources",
            "Prepare and label training data",
            "Define success criteria and metrics",
            "Data quality review",
        ],
        "Current-State Analysis": [
            "Map current process steps",
            "Identify waste and bottlenecks",
            "Gather stakeholder input",
            "Document baseline metrics",
        ],
    }
    default = [
        f"Phase {phase_index + 1} milestone 1",
        f"Phase {phase_index + 1} milestone 2",
        f"Phase {phase_index + 1} milestone 3",
    ]
    titles = milestones_map.get(phase_name, default)
    return [
        {"title": t, "description": "", "status": "not_started", "sort_order": i}
        for i, t in enumerate(titles)
    ]


def _infer_intervention_family(intervention_name: str) -> str:
    name = (intervention_name or "").lower()
    if any(kw in name for kw in ["rpa", "workflow automation", "automation", "robotic"]):
        return "Workflow_Automation"
    if any(kw in name for kw in ["ai", "machine learning", "ml", "deep learning", "llm", "gen ai"]):
        return "AI"
    if any(kw in name for kw in ["software", "platform", "crm", "erp", "system", "saas"]):
        return "Software"
    if any(kw in name for kw in ["process redesign", "reengineering", "lean", "six sigma"]):
        return "Process_Redesign"
    if any(kw in name for kw in ["staffing", "hiring", "training", "outsource"]):
        return "Staffing"
    return "Workflow_Automation"


def create_workspace(
    recommendation_id: str,
    intervention_id: str,
    intended_goal: str = "",
    expected_timeline: str = "",
) -> dict:
    rec_data = load_recommendation(recommendation_id)
    if not rec_data:
        raise ValueError(f"Recommendation {recommendation_id} not found")

    scored = rec_data.get("scored_interventions", [])
    selected = next(
        (s for s in scored if s.get("intervention_id") == intervention_id),
        None,
    )
    if not selected:
        raise ValueError(f"Intervention {intervention_id} not found in recommendation")

    intervention_name = selected.get("intervention_name", "")
    family = _infer_intervention_family(intervention_name)

    ws_id = str(uuid.uuid4())
    phases_data = _phase_templates(family)
    session = get_session()
    try:
        ws = ImplementationWorkspace(
            id=ws_id,
            recommendation_id=recommendation_id,
            selected_intervention_id=intervention_id,
            selected_intervention_name=intervention_name,
            intended_goal=intended_goal or selected.get("expected_impact", ""),
            expected_timeline=expected_timeline or selected.get("estimated_timeframe", ""),
            known_risks=selected.get("top_risks", []),
            plan_version=1,
            assessment_snapshot=rec_data.get("assessment_summary", {}),
            score_breakdown_snapshot=selected.get("score_breakdown", {}),
            supporting_evidence_ids=[
                c.get("organization_name", "")
                for c in selected.get("comparable_implementations", [])
            ],
            comparable_implementations_snapshot=selected.get("comparable_implementations", []),
        )
        session.add(ws)

        phases = []
        milestones = []
        for pi, phase_tpl in enumerate(phases_data):
            phase_id = str(uuid.uuid4())
            phase = ImplementationPhase(
                id=phase_id,
                workspace_id=ws_id,
                name=phase_tpl["name"],
                objective=phase_tpl["objective"],
                expected_duration=phase_tpl.get("duration", ""),
                sort_order=pi,
                status="not_started" if pi > 0 else "in_progress",
            )
            session.add(phase)
            phases.append(phase)

            for mi, mt in enumerate(_generate_milestones(phase_tpl["name"], pi)):
                milestone_id = str(uuid.uuid4())
                milestone = ImplementationMilestone(
                    id=milestone_id,
                    workspace_id=ws_id,
                    phase_id=phase_id,
                    title=mt["title"],
                    status="not_started",
                    sort_order=mi,
                )
                session.add(milestone)
                milestones.append(milestone)

        ws.current_phase = phases[0].name if phases else ""

        plan_version = ImplementationPlanVersion(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            version_number=1,
            phases=[{"id": p.id, "name": p.name} for p in phases],
            milestones=[{"id": m.id, "title": m.title, "phase_id": m.phase_id} for m in milestones],
            change_description="Initial implementation plan",
        )
        session.add(plan_version)
        session.commit()

        return {
            "id": ws_id,
            "recommendation_id": recommendation_id,
            "selected_intervention_id": intervention_id,
            "selected_intervention_name": intervention_name,
            "status": ws.status,
            "current_phase": ws.current_phase,
            "overall_progress": 0.0,
            "intended_goal": ws.intended_goal,
            "expected_timeline": ws.expected_timeline,
            "plan_version": 1,
            "phases_count": len(phases),
            "milestones_count": len(milestones),
            "created_at": ws.created_at.isoformat() if ws.created_at else "",
        }
    finally:
        session.close()


def get_workspace(workspace_id: str) -> Optional[dict]:
    session = get_session()
    try:
        ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
        if not ws:
            return None
        return {
            "id": ws.id,
            "recommendation_id": ws.recommendation_id,
            "selected_intervention_id": ws.selected_intervention_id,
            "selected_intervention_name": ws.selected_intervention_name,
            "status": ws.status,
            "current_phase": ws.current_phase,
            "overall_progress": ws.overall_progress,
            "intended_goal": ws.intended_goal,
            "expected_timeline": ws.expected_timeline,
            "known_risks": ws.known_risks or [],
            "plan_version": ws.plan_version,
            "created_at": ws.created_at.isoformat() if ws.created_at else "",
            "updated_at": ws.updated_at.isoformat() if ws.updated_at else "",
        }
    finally:
        session.close()


def get_phases(workspace_id: str) -> list[dict]:
    session = get_session()
    try:
        phases = session.query(ImplementationPhase).filter_by(
            workspace_id=workspace_id
        ).order_by(ImplementationPhase.sort_order).all()
        result = []
        for p in phases:
            milestones = session.query(ImplementationMilestone).filter_by(
                phase_id=p.id
            ).order_by(ImplementationMilestone.sort_order).all()
            result.append({
                "id": p.id,
                "name": p.name,
                "objective": p.objective,
                "description": p.description,
                "expected_duration": p.expected_duration,
                "prerequisites": p.prerequisites or [],
                "risks": p.risks or [],
                "status": p.status,
                "sort_order": p.sort_order,
                "milestones": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "description": m.description,
                        "status": m.status,
                        "target_date": m.target_date or "",
                        "owner": m.owner or "",
                        "notes": m.notes or "",
                        "sort_order": m.sort_order,
                    }
                    for m in milestones
                ],
            })
        return result
    finally:
        session.close()


def update_milestone_status(
    workspace_id: str,
    milestone_id: str,
    status: str,
    notes: str = "",
    owner: str = "",
) -> dict:
    if status not in MILESTONE_STATUSES:
        raise ValueError(f"Invalid milestone status: {status}")

    session = get_session()
    try:
        milestone = session.query(ImplementationMilestone).filter_by(
            id=milestone_id, workspace_id=workspace_id
        ).first()
        if not milestone:
            raise ValueError(f"Milestone {milestone_id} not found")

        milestone.status = status
        if notes:
            milestone.notes = notes
        if owner:
            milestone.owner = owner
        if status == "completed" and not milestone.completion_date:
            milestone.completion_date = datetime.utcnow()

        phase = session.query(ImplementationPhase).filter_by(
            id=milestone.phase_id
        ).first()
        if phase and status == "completed":
            siblings = session.query(ImplementationMilestone).filter_by(
                phase_id=phase.id
            ).all()
            if all(m.status == "completed" for m in siblings):
                phase.status = "completed"
                phases = session.query(ImplementationPhase).filter_by(
                    workspace_id=workspace_id
                ).order_by(ImplementationPhase.sort_order).all()
                current_idx = next(
                    (i for i, p in enumerate(phases) if p.id == phase.id), None
                )
                if current_idx is not None and current_idx + 1 < len(phases):
                    next_phase = phases[current_idx + 1]
                    if next_phase.status == "not_started":
                        next_phase.status = "in_progress"
                        ws = session.query(ImplementationWorkspace).filter_by(
                            id=workspace_id
                        ).first()
                        if ws:
                            ws.current_phase = next_phase.name

        _recalculate_progress(session, workspace_id)
        session.commit()

        return {
            "id": milestone.id,
            "status": milestone.status,
            "notes": milestone.notes,
        }
    finally:
        session.close()


def _recalculate_progress(session, workspace_id: str):
    ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
    if not ws:
        return

    phases = session.query(ImplementationPhase).filter_by(
        workspace_id=workspace_id
    ).order_by(ImplementationPhase.sort_order).all()

    if not phases:
        ws.overall_progress = 0.0
        return

    total_milestones = 0
    completed_milestones = 0
    for phase in phases:
        milestones = session.query(ImplementationMilestone).filter_by(
            phase_id=phase.id
        ).all()
        total_milestones += len(milestones)
        completed_milestones += sum(1 for m in milestones if m.status == "completed")

    if total_milestones > 0:
        ws.overall_progress = round(
            (completed_milestones / total_milestones) * 100, 1
        )
    else:
        ws.overall_progress = 0.0


def add_progress_update(
    workspace_id: str,
    update_text: str,
    phase_id: str = "",
    milestone_id: str = "",
    progress_status: str = "",
    blocker_indicator: bool = False,
) -> dict:
    session = get_session()
    try:
        pu = ProgressUpdate(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            phase_id=phase_id or None,
            milestone_id=milestone_id or None,
            update_text=update_text,
            progress_status=progress_status,
            blocker_indicator=blocker_indicator,
        )
        session.add(pu)
        session.commit()
        return {"id": pu.id, "created_at": pu.created_at.isoformat() if pu.created_at else ""}
    finally:
        session.close()


def add_blocker(
    workspace_id: str,
    title: str,
    description: str,
    severity: str = "medium",
    milestone_id: str = "",
    suggested_response: str = "",
) -> dict:
    session = get_session()
    try:
        blocker = Blocker(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            milestone_id=milestone_id or None,
            title=title,
            description=description,
            severity=severity,
            suggested_response=suggested_response,
        )
        session.add(blocker)
        if milestone_id:
            milestone = session.query(ImplementationMilestone).filter_by(
                id=milestone_id
            ).first()
            if milestone and milestone.status != "blocked":
                milestone.status = "blocked"
        session.commit()
        return {"id": blocker.id, "status": "open"}
    finally:
        session.close()


def resolve_blocker(blocker_id: str, resolution_notes: str) -> dict:
    session = get_session()
    try:
        blocker = session.query(Blocker).filter_by(id=blocker_id).first()
        if not blocker:
            raise ValueError(f"Blocker {blocker_id} not found")
        blocker.status = "resolved"
        blocker.resolution_notes = resolution_notes
        blocker.resolved_date = datetime.utcnow()
        session.commit()
        return {"id": blocker.id, "status": "resolved"}
    finally:
        session.close()


def get_blockers(workspace_id: str) -> list[dict]:
    session = get_session()
    try:
        blockers = session.query(Blocker).filter_by(
            workspace_id=workspace_id
        ).order_by(Blocker.date_identified.desc()).all()
        return [
            {
                "id": b.id,
                "title": b.title,
                "description": b.description,
                "severity": b.severity,
                "status": b.status,
                "milestone_id": b.milestone_id,
                "suggested_response": b.suggested_response,
                "resolution_notes": b.resolution_notes,
                "date_identified": b.date_identified.isoformat() if b.date_identified else "",
                "resolved_date": b.resolved_date.isoformat() if b.resolved_date else "",
            }
            for b in blockers
        ]
    finally:
        session.close()


def record_decision(
    workspace_id: str,
    decision: str,
    context: str = "",
    alternatives_considered: list[str] = None,
    rationale: str = "",
    milestone_id: str = "",
    decision_maker: str = "",
    evidence_used: list[str] = None,
    expected_consequence: str = "",
) -> dict:
    session = get_session()
    try:
        dr = DecisionRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            milestone_id=milestone_id or None,
            decision=decision,
            context=context,
            alternatives_considered=alternatives_considered or [],
            rationale=rationale,
            decision_maker=decision_maker,
            evidence_used=evidence_used or [],
            expected_consequence=expected_consequence,
        )
        session.add(dr)
        session.commit()
        return {"id": dr.id, "created_at": dr.created_at.isoformat() if dr.created_at else ""}
    finally:
        session.close()


def add_metric_measurement(
    workspace_id: str,
    metric_id: str,
    value: float,
    measurement_date: str = "",
) -> dict:
    session = get_session()
    try:
        metric = session.query(SuccessMetric).filter_by(
            id=metric_id, workspace_id=workspace_id
        ).first()
        if not metric:
            raise ValueError(f"Metric {metric_id} not found")
        metric.current_value = value
        if measurement_date:
            try:
                metric.measurement_date = datetime.fromisoformat(measurement_date)
            except ValueError:
                pass
        if metric.target_value and metric.baseline_value is not None:
            target = metric.target_value
            baseline = metric.baseline_value
            current = value
            improvement_dir = target > baseline
            if improvement_dir:
                if current >= target:
                    metric.status = "achieved"
                elif current >= baseline + (target - baseline) * 0.5:
                    metric.status = "on_track"
                else:
                    metric.status = "below_target"
            else:
                if current <= target:
                    metric.status = "achieved"
                elif current <= baseline - abs(target - baseline) * 0.5:
                    metric.status = "on_track"
                else:
                    metric.status = "below_target"
        if current is not None and current == 0 and metric.status == "not_measured":
            metric.status = "below_target"
        session.commit()
        return {
            "id": metric.id,
            "current_value": metric.current_value,
            "status": metric.status,
        }
    finally:
        session.close()


def get_success_metrics(workspace_id: str) -> list[dict]:
    session = get_session()
    try:
        metrics = session.query(SuccessMetric).filter_by(
            workspace_id=workspace_id
        ).all()
        return [
            {
                "id": m.id,
                "name": m.name,
                "baseline_value": m.baseline_value,
                "target_value": m.target_value,
                "current_value": m.current_value,
                "unit": m.unit,
                "status": m.status,
                "measurement_date": m.measurement_date.isoformat() if m.measurement_date else "",
                "data_source": m.data_source,
                "notes": m.notes,
            }
            for m in metrics
        ]
    finally:
        session.close()


def send_companion_message(workspace_id: str, content: str) -> dict:
    session = get_session()
    try:
        ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
        if not ws:
            raise ValueError(f"Workspace {workspace_id} not found")

        user_msg = CompanionMessage(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            role="user",
            content=content,
        )
        session.add(user_msg)

        response_content = _companion_response(workspace_id, content, session)
        evidence_ids = _get_relevant_evidence(workspace_id, content, session)

        companion_msg = CompanionMessage(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            role="assistant",
            content=response_content,
            message_type="chat",
            evidence_ids_used=evidence_ids,
        )
        session.add(companion_msg)
        session.commit()

        return {
            "id": companion_msg.id,
            "workspace_id": workspace_id,
            "role": "assistant",
            "content": response_content,
            "evidence_ids_used": evidence_ids,
            "created_at": companion_msg.created_at.isoformat() if companion_msg.created_at else "",
        }
    finally:
        session.close()


def _companion_response(workspace_id: str, user_message: str, session) -> str:
    ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
    phases = session.query(ImplementationPhase).filter_by(
        workspace_id=workspace_id
    ).order_by(ImplementationPhase.sort_order).all()
    milestones = session.query(ImplementationMilestone).filter_by(
        workspace_id=workspace_id
    ).all()
    blockers = session.query(Blocker).filter_by(
        workspace_id=workspace_id, status="open"
    ).all()

    completed = sum(1 for m in milestones if m.status == "completed")
    total = len(milestones)
    blocked = [m for m in milestones if m.status == "blocked"]
    current_phase_name = ws.current_phase if ws else ""

    msg_lower = user_message.lower()

    if any(kw in msg_lower for kw in ["next", "what should", "what do", "recommend", "suggest"]):
        lines = [f"Based on your current progress ({completed}/{total} milestones):"]
        if blocked:
            lines.append(f"  - {len(blocked)} milestone(s) are blocked. Resolving these should be the priority.")
            for b in blocked[:2]:
                lines.append(f"    * {b.title}")
        if current_phase_name:
            lines.append(f"  - You are in the '{current_phase_name}' phase.")
        active_phase = next((p for p in phases if p.status == "in_progress"), None)
        if active_phase:
            phase_milestones = [m for m in milestones if m.phase_id == active_phase.id]
            not_started = [m for m in phase_milestones if m.status == "not_started"]
            if not_started:
                lines.append(f"  - Next milestone: '{not_started[0].title}'")
        lines.append(f"\nConsider completing the current phase milestones before moving to the next phase.")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["risk", "concern", "worry"]):
        lines = ["Key risks to consider at this stage:"]
        if ws and ws.known_risks:
            for r in (ws.known_risks or [])[:3]:
                lines.append(f"  - {r}")
        lines.append(f"\nFrom comparable implementations, common challenges include:")
        lines.append(f"  - Incomplete process documentation")
        lines.append(f"  - Stakeholder resistance to change")
        lines.append(f"  - Underestimating integration effort")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["progress", "summary", "status", "update"]):
        return _progress_summary_text(ws, phases, milestones, blockers)

    if any(kw in msg_lower for kw in ["change", "adjust", "modify"]):
        return (
            f"I see you're considering a plan adjustment. Here's what I'd recommend:\n\n"
            f"Current status: {completed}/{total} milestones complete.\n"
            f"Rather than changing the overall approach, consider:\n"
            f"  1. Complete the current phase milestones\n"
            f"  2. Log any blockers you're encountering\n"
            f"  3. If conditions have materially changed, I can propose a formal plan change\n\n"
            f"Would you like me to draft a plan change proposal?"
        )

    return (
        f"You're working on '{ws.selected_intervention_name if ws else ''}'. "
        f"Current phase: {current_phase_name or 'Not started'}. "
        f"Progress: {completed}/{total} milestones. "
        f"Open blockers: {len(blockers)}. "
        f"\n\nI can help with:\n"
        f"- What to do next\n"
        f"- Identifying risks\n"
        f"- Progress summaries\n"
        f"- Drafting meeting agendas or status updates\n"
        f"- Proposing plan adjustments"
    )


def _progress_summary_text(ws, phases, milestones, blockers) -> str:
    completed = [m for m in milestones if m.status == "completed"]
    blocked = [m for m in milestones if m.status == "blocked"]
    decisions_made = []  # Would query decisions in full impl
    lines = [
        f"**Progress Summary**",
        f"Intervention: {ws.selected_intervention_name if ws else 'N/A'}",
        f"Current Phase: {ws.current_phase if ws else 'Not started'}",
        f"Overall Progress: {ws.overall_progress if ws else 0}%",
        f"",
        f"Completed: {len(completed)} milestones",
        f"Open Blockers: {len(blockers)}",
        f"",
    ]
    if completed:
        lines.append("Recent completions:")
        for m in completed[-3:]:
            lines.append(f"  - {m.title}")
    if blocked:
        lines.append("\nBlocked:")
        for b in blocked[:3]:
            lines.append(f"  - {b.title}")
    return "\n".join(lines)


def _get_relevant_evidence(workspace_id: str, user_message: str, session) -> list[str]:
    ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
    if ws and ws.supporting_evidence_ids:
        return ws.supporting_evidence_ids[:3]
    return []


def get_conversation_history(workspace_id: str, limit: int = 50) -> list[dict]:
    session = get_session()
    try:
        messages = session.query(CompanionMessage).filter_by(
            workspace_id=workspace_id
        ).order_by(CompanionMessage.created_at.asc()).limit(limit).all()
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "evidence_ids_used": m.evidence_ids_used or [],
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ]
    finally:
        session.close()


def propose_plan_change(
    workspace_id: str,
    reason: str = "",
    affected_phases: list[str] = None,
    expected_impact: str = "",
    supporting_evidence: list[str] = None,
    introduced_risks: list[str] = None,
) -> dict:
    session = get_session()
    try:
        ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
        if not ws:
            raise ValueError(f"Workspace {workspace_id} not found")

        phases = session.query(ImplementationPhase).filter_by(
            workspace_id=workspace_id
        ).order_by(ImplementationPhase.sort_order).all()
        milestones = session.query(ImplementationMilestone).filter_by(
            workspace_id=workspace_id
        ).all()

        change = ProposedPlanChange(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            proposed_by="companion",
            proposed_phases=[{"id": p.id, "name": p.name, "status": p.status} for p in phases],
            proposed_milestones=[{"id": m.id, "title": m.title, "status": m.status} for m in milestones],
            reason=reason or "Plan adjustment based on changing conditions",
            affected_phases=affected_phases or [],
            expected_impact=expected_impact or "",
            supporting_evidence=supporting_evidence or [],
            introduced_risks=introduced_risks or [],
        )
        session.add(change)
        session.commit()
        return {
            "id": change.id,
            "reason": change.reason,
            "status": "pending",
            "created_at": change.created_at.isoformat() if change.created_at else "",
        }
    finally:
        session.close()


def accept_plan_change(change_id: str) -> dict:
    session = get_session()
    try:
        change = session.query(ProposedPlanChange).filter_by(id=change_id).first()
        if not change:
            raise ValueError(f"Plan change {change_id} not found")
        if change.status != "pending":
            raise ValueError(f"Plan change is already {change.status}")

        change.status = "accepted"
        change.accepted_at = datetime.utcnow()

        ws = session.query(ImplementationWorkspace).filter_by(
            id=change.workspace_id
        ).first()
        if ws:
            ws.plan_version = (ws.plan_version or 1) + 1

            for phase_data in change.proposed_phases or []:
                phase = session.query(ImplementationPhase).filter_by(
                    id=phase_data.get("id"),
                    workspace_id=change.workspace_id,
                ).first()
                if phase:
                    phase.status = phase_data.get("status", phase.status)

        new_version = ImplementationPlanVersion(
            id=str(uuid.uuid4()),
            workspace_id=change.workspace_id,
            version_number=ws.plan_version if ws else 2,
            phases=change.proposed_phases or [],
            milestones=change.proposed_milestones or [],
            change_description=change.reason,
            proposed_by=change.proposed_by,
            accepted_at=datetime.utcnow(),
        )
        session.add(new_version)
        session.commit()

        return {
            "change_id": change.id,
            "status": "accepted",
            "new_plan_version": ws.plan_version if ws else 2,
        }
    finally:
        session.close()


def generate_progress_summary(workspace_id: str) -> dict:
    session = get_session()
    try:
        ws = session.query(ImplementationWorkspace).filter_by(id=workspace_id).first()
        if not ws:
            raise ValueError(f"Workspace {workspace_id} not found")

        phases = session.query(ImplementationPhase).filter_by(
            workspace_id=workspace_id
        ).order_by(ImplementationPhase.sort_order).all()
        milestones = session.query(ImplementationMilestone).filter_by(
            workspace_id=workspace_id
        ).all()
        blockers = session.query(Blocker).filter_by(
            workspace_id=workspace_id, status="open"
        ).all()
        decisions = session.query(DecisionRecord).filter_by(
            workspace_id=workspace_id
        ).all()
        metrics = session.query(SuccessMetric).filter_by(
            workspace_id=workspace_id
        ).all()

        completed = [m for m in milestones if m.status == "completed"]
        blocked = [m for m in milestones if m.status == "blocked"]

        return {
            "workspace_id": workspace_id,
            "work_completed": [m.title for m in completed[-5:]],
            "current_phase": ws.current_phase or "",
            "open_blockers": len(blockers),
            "decisions_made": len(decisions),
            "overall_progress": ws.overall_progress or 0.0,
            "next_recommended_action": _next_action_text(phases, milestones),
            "metric_status": [
                {"name": m.name, "status": m.status, "current": m.current_value, "target": m.target_value}
                for m in metrics
            ],
            "changes_from_previous": f"Plan version {ws.plan_version}",
        }
    finally:
        session.close()


def _next_action_text(phases: list, milestones: list) -> str:
    for phase in phases:
        if phase.status == "in_progress":
            phase_milestones = [m for m in milestones if m.phase_id == phase.id]
            not_started = [m for m in phase_milestones if m.status == "not_started"]
            blocked = [m for m in phase_milestones if m.status == "blocked"]
            if blocked:
                return f"Resolve blockers in '{phase.name}': {blocked[0].title}"
            if not_started:
                return f"Begin milestone: {not_started[0].title}"
            return f"Complete '{phase.name}' phase review"
    return "Start the first phase"
