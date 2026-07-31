from datetime import datetime
from sqlalchemy import Column, String, Text, JSON, Boolean, DateTime
from compass_collector.database import Base


class ImplementationPlan(Base):
    __tablename__ = "implementation_plans"

    id = Column(String, primary_key=True)
    analysis_id = Column(String, index=True)
    decision_id = Column(String, index=True)
    selected_path = Column(String, default="internal")
    partner_id = Column(String, default="")
    partner_name = Column(String, default="")
    contact_email = Column(String, default="")
    organization = Column(String, default="")
    stages = Column(JSON, default=list)
    status = Column(String, default="active")
    partner_status = Column(String, default="not_requested")
    invite_token = Column(String, default="")
    invite_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImplementationRequest(Base):
    __tablename__ = "implementation_requests"

    id = Column(String, primary_key=True)
    implementation_id = Column(String, index=True)
    partner_id = Column(String, default="")
    partner_name = Column(String, default="")
    contact_name = Column(String, default="")
    contact_email = Column(String, default="")
    organization = Column(String, default="")
    requested_timeline = Column(String, default="")
    notes = Column(Text, default="")
    consent = Column(Boolean, default=False)
    status = Column(String, default="submitted")
    notification = Column(JSON, default=dict)
    audit = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class SavedDecision(Base):
    __tablename__ = "saved_decisions"

    id = Column(String, primary_key=True)
    analysis_id = Column(String, index=True)
    email = Column(String, default="")
    resume_token = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
