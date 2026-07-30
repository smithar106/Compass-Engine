from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, Float, Integer, JSON, ForeignKey
from compass_collector.database import Base


class ImplementationWorkspace(Base):
    __tablename__ = "implementation_workspaces"

    id = Column(String, primary_key=True)
    organization_id = Column(String, default="default")
    user_id = Column(String, default="default")
    recommendation_id = Column(String, index=True)
    selected_intervention_id = Column(String)
    selected_intervention_name = Column(String, default="")
    status = Column(String, default="active")
    current_phase = Column(String, default="")
    overall_progress = Column(Float, default=0.0)
    intended_goal = Column(Text, default="")
    expected_timeline = Column(String, default="")
    known_risks = Column(JSON, default=list)
    dependencies = Column(JSON, default=list)
    plan_version = Column(Integer, default=1)
    assessment_snapshot = Column(JSON, default=dict)
    score_breakdown_snapshot = Column(JSON, default=dict)
    supporting_evidence_ids = Column(JSON, default=list)
    comparable_implementations_snapshot = Column(JSON, default=list)
    success_metrics_targets = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImplementationPlanVersion(Base):
    __tablename__ = "implementation_plan_versions"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    version_number = Column(Integer, default=1)
    phases = Column(JSON, default=list)
    milestones = Column(JSON, default=list)
    change_description = Column(Text, default="")
    proposed_by = Column(String, default="system")
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImplementationPhase(Base):
    __tablename__ = "implementation_phases"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    plan_version_id = Column(String, default="")
    name = Column(String, default="")
    objective = Column(Text, default="")
    description = Column(Text, default="")
    expected_duration = Column(String, default="")
    prerequisites = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    evidence_references = Column(JSON, default=list)
    status = Column(String, default="not_started")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImplementationMilestone(Base):
    __tablename__ = "implementation_milestones"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    phase_id = Column(String, index=True)
    title = Column(String, default="")
    description = Column(Text, default="")
    status = Column(String, default="not_started")
    target_date = Column(String, nullable=True)
    completion_date = Column(DateTime, nullable=True)
    owner = Column(String, default="")
    notes = Column(Text, default="")
    blockers = Column(JSON, default=list)
    supporting_evidence = Column(JSON, default=list)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProgressUpdate(Base):
    __tablename__ = "progress_updates"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    phase_id = Column(String, nullable=True)
    milestone_id = Column(String, nullable=True)
    update_text = Column(Text, default="")
    progress_status = Column(String, default="")
    blocker_indicator = Column(Boolean, default=False)
    uploaded_file_path = Column(String, nullable=True)
    decision_record_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Blocker(Base):
    __tablename__ = "implementation_blockers"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    milestone_id = Column(String, nullable=True)
    title = Column(String, default="")
    description = Column(Text, default="")
    severity = Column(String, default="medium")
    status = Column(String, default="open")
    date_identified = Column(DateTime, default=datetime.utcnow)
    suggested_response = Column(Text, default="")
    evidence_rationale = Column(Text, default="")
    resolution_notes = Column(Text, default="")
    resolved_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DecisionRecord(Base):
    __tablename__ = "implementation_decisions"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    milestone_id = Column(String, nullable=True)
    decision = Column(Text, default="")
    context = Column(Text, default="")
    alternatives_considered = Column(JSON, default=list)
    rationale = Column(Text, default="")
    decision_maker = Column(String, default="")
    evidence_used = Column(JSON, default=list)
    expected_consequence = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkspaceDocument(Base):
    __tablename__ = "workspace_documents"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    original_filename = Column(String, default="")
    file_path = Column(String, default="")
    file_type = Column(String, default="")
    extracted_content = Column(Text, default="")
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class SuccessMetric(Base):
    __tablename__ = "workspace_success_metrics"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    name = Column(String, default="")
    baseline_value = Column(Float, nullable=True)
    target_value = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    unit = Column(String, default="")
    measurement_date = Column(DateTime, nullable=True)
    data_source = Column(String, default="")
    notes = Column(Text, default="")
    status = Column(String, default="not_measured")
    created_at = Column(DateTime, default=datetime.utcnow)


class CompanionMessage(Base):
    __tablename__ = "companion_messages"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    role = Column(String, default="user")
    content = Column(Text, default="")
    message_type = Column(String, default="chat")
    evidence_ids_used = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProposedPlanChange(Base):
    __tablename__ = "proposed_plan_changes"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, index=True)
    proposed_by = Column(String, default="companion")
    proposed_phases = Column(JSON, default=list)
    proposed_milestones = Column(JSON, default=list)
    reason = Column(Text, default="")
    affected_phases = Column(JSON, default=list)
    expected_impact = Column(Text, default="")
    supporting_evidence = Column(JSON, default=list)
    introduced_risks = Column(JSON, default=list)
    status = Column(String, default="pending")
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
