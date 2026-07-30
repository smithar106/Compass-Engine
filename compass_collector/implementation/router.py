import logging
from fastapi import APIRouter, HTTPException
from compass_collector.implementation.schemas import (
    CreateWorkspaceRequest,
    UpdateMilestoneRequest,
    AddProgressUpdateRequest,
    AddBlockerRequest,
    ResolveBlockerRequest,
    RecordDecisionRequest,
    AddMetricMeasurementRequest,
    CompanionMessageRequest,
    AcceptPlanChangeRequest,
)
from compass_collector.implementation.service import (
    create_workspace,
    get_workspace,
    get_phases,
    update_milestone_status,
    add_progress_update,
    add_blocker,
    resolve_blocker,
    get_blockers,
    record_decision,
    add_metric_measurement,
    get_success_metrics,
    send_companion_message,
    get_conversation_history,
    propose_plan_change,
    accept_plan_change,
    generate_progress_summary,
)

logger = logging.getLogger("compass-engine.implementation")
router = APIRouter(prefix="/api/workspaces", tags=["implementation"])


@router.post("")
def api_create_workspace(req: CreateWorkspaceRequest):
    try:
        result = create_workspace(
            recommendation_id=req.recommendation_id,
            intervention_id=req.selected_intervention_id,
            intended_goal=req.intended_goal,
            expected_timeline=req.expected_timeline,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workspace_id}")
def api_get_workspace(workspace_id: str):
    result = get_workspace(workspace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result


@router.get("/{workspace_id}/phases")
def api_get_phases(workspace_id: str):
    return get_phases(workspace_id)


@router.patch("/{workspace_id}/milestones/{milestone_id}")
def api_update_milestone(workspace_id: str, milestone_id: str, req: UpdateMilestoneRequest):
    try:
        return update_milestone_status(
            workspace_id=workspace_id,
            milestone_id=milestone_id,
            status=req.status,
            notes=req.notes,
            owner=req.owner,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workspace_id}/progress")
def api_add_progress(workspace_id: str, req: AddProgressUpdateRequest):
    return add_progress_update(
        workspace_id=workspace_id,
        update_text=req.update_text,
        phase_id=req.phase_id,
        milestone_id=req.milestone_id,
        progress_status=req.progress_status,
        blocker_indicator=req.blocker_indicator,
    )


@router.post("/{workspace_id}/blockers")
def api_add_blocker(workspace_id: str, req: AddBlockerRequest):
    return add_blocker(
        workspace_id=workspace_id,
        title=req.title,
        description=req.description,
        severity=req.severity,
        milestone_id=req.milestone_id,
        suggested_response=req.suggested_response,
    )


@router.get("/{workspace_id}/blockers")
def api_get_blockers(workspace_id: str):
    return get_blockers(workspace_id)


@router.post("/blockers/{blocker_id}/resolve")
def api_resolve_blocker(blocker_id: str, req: ResolveBlockerRequest):
    try:
        return resolve_blocker(blocker_id, req.resolution_notes)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{workspace_id}/decisions")
def api_record_decision(workspace_id: str, req: RecordDecisionRequest):
    return record_decision(
        workspace_id=workspace_id,
        decision=req.decision,
        context=req.context,
        alternatives_considered=req.alternatives_considered,
        rationale=req.rationale,
        milestone_id=req.milestone_id,
        decision_maker=req.decision_maker,
        evidence_used=req.evidence_used,
        expected_consequence=req.expected_consequence,
    )


@router.post("/{workspace_id}/metrics/{metric_id}/measure")
def api_add_measurement(workspace_id: str, metric_id: str, req: AddMetricMeasurementRequest):
    try:
        return add_metric_measurement(
            workspace_id=workspace_id,
            metric_id=metric_id,
            value=req.value,
            measurement_date=req.measurement_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{workspace_id}/metrics")
def api_get_metrics(workspace_id: str):
    return get_success_metrics(workspace_id)


@router.post("/{workspace_id}/companion/messages")
def api_send_message(workspace_id: str, req: CompanionMessageRequest):
    try:
        return send_companion_message(workspace_id, req.content)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{workspace_id}/companion/history")
def api_get_history(workspace_id: str, limit: int = 50):
    return get_conversation_history(workspace_id, limit=limit)


@router.post("/{workspace_id}/plan-changes/propose")
def api_propose_plan_change(workspace_id: str):
    try:
        return propose_plan_change(workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/plan-changes/{change_id}/accept")
def api_accept_plan_change(change_id: str):
    try:
        return accept_plan_change(change_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workspace_id}/progress-summary")
def api_progress_summary(workspace_id: str):
    try:
        return generate_progress_summary(workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
