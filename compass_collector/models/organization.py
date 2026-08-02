from datetime import datetime
from sqlalchemy import Column, String, Text, JSON, DateTime
from compass_collector.database import Base


class OrganizationProfileRecord(Base):
    """Persisted canonical organization profile (Phase 4 resolution output)."""

    __tablename__ = "organization_profiles"

    id = Column(String, primary_key=True)
    canonical_name = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    domain = Column(String, default="")
    primary_industry = Column(String, default="")
    industry_subsector = Column(String, default="")
    profile_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
