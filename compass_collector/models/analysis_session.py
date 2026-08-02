from datetime import datetime
from sqlalchemy import Column, String, Text, JSON, DateTime
from compass_collector.database import Base


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id = Column(String, primary_key=True)
    original_input = Column(Text, default="")
    attachments = Column(JSON, default=list)
    normalization = Column(JSON, default=dict)
    edits = Column(JSON, default=dict)
    inferred = Column(JSON, default=list)
    questions = Column(JSON, default=list)
    answers = Column(JSON, default=dict)
    organization = Column(JSON, nullable=True)
    evidence_ids = Column(JSON, default=list)
    retrieval_snapshots = Column(JSON, default=list)
    decision = Column(JSON, nullable=True)
    status = Column(String, default="awaiting_confirmation")
    scoring_version = Column(String, default="")
    engine_version = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
