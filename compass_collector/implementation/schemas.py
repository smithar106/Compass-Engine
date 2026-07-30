from pydantic import BaseModel, Field
from typing import Optional


class CreateWorkspaceRequest(BaseModel):
    recommendation_id: str = ""
    selected_intervention_id: str = ""
    intended_goal: str = ""
    expected_timeline: str = ""


class WorkspaceResponse(BaseModel):
    id: str = ""
    recommendation_id: str = ""
    selected_intervention_id: str = ""
    selected_intervention_name: str = ""
    status: str = "active"
    current_phase: str = ""
    overall_progress: float = 0.0
    intended_goal: str = ""
    expected_timeline: str = ""
    known_risks: list[str] = []
    plan_version: int = 1
    created_at: str = ""


class PhaseResponse(BaseModel):
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    objective: str = ""
    description: str = ""
    expected_duration: str = ""
    prerequisites: list[str] = []
    risks: list[str] = []
    status: str = "not_started"
    sort_order: int = 0


class MilestoneResponse(BaseModel):
    id: str = ""
    workspace_id: str = ""
    phase_id: str = ""
    title: str = ""
    description: str = ""
    status: str = "not_started"
    target_date: str = ""
    completion_date: str = ""
    owner: str = ""
    notes: str = ""
    sort_order: int = 0


class UpdateMilestoneRequest(BaseModel):
    status: str = ""
    notes: str = ""
    owner: str = ""


class AddProgressUpdateRequest(BaseModel):
    phase_id: str = ""
    milestone_id: str = ""
    update_text: str = ""
    progress_status: str = ""
    blocker_indicator: bool = False


class AddBlockerRequest(BaseModel):
    milestone_id: str = ""
    title: str = ""
    description: str = ""
    severity: str = "medium"
    suggested_response: str = ""


class ResolveBlockerRequest(BaseModel):
    resolution_notes: str = ""


class RecordDecisionRequest(BaseModel):
    milestone_id: str = ""
    decision: str = ""
    context: str = ""
    alternatives_considered: list[str] = []
    rationale: str = ""
    decision_maker: str = ""
    evidence_used: list[str] = []
    expected_consequence: str = ""


class AddMetricMeasurementRequest(BaseModel):
    metric_id: str = ""
    value: float = 0.0
    measurement_date: str = ""


class CompanionMessageRequest(BaseModel):
    content: str = ""


class CompanionMessageResponse(BaseModel):
    id: str = ""
    workspace_id: str = ""
    role: str = ""
    content: str = ""
    message_type: str = ""
    evidence_ids_used: list[str] = []
    created_at: str = ""


class ProposedPlanChangeResponse(BaseModel):
    id: str = ""
    workspace_id: str = ""
    proposed_by: str = ""
    reason: str = ""
    affected_phases: list[str] = []
    expected_impact: str = ""
    supporting_evidence: list[str] = []
    introduced_risks: list[str] = []
    status: str = "pending"
    created_at: str = ""


class AcceptPlanChangeRequest(BaseModel):
    change_id: str = ""


class ProgressSummaryResponse(BaseModel):
    workspace_id: str = ""
    work_completed: list[str] = []
    current_phase: str = ""
    open_blockers: int = 0
    decisions_made: int = 0
    overall_progress: float = 0.0
    next_recommended_action: str = ""
    metric_status: list[dict] = []
    changes_from_previous: str = ""
