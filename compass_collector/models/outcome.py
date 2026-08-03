from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, Float, DateTime
from compass_collector.database import Base


class DecisionOutcome(Base):
    """Customer outcome feedback after acting on a recommendation.

    This is Compass's most valuable proprietary dataset — the internal evidence
    moat. It records whether the customer accepted the recommendation, what they
    implemented, whether it followed the Blueprint, realized cost/duration/
    result, unexpected constraints, and whether Compass would re-recommend.
    """

    __tablename__ = "decision_outcomes"

    id = Column(String, primary_key=True)
    recommendation_id = Column(String, index=True, nullable=False)
    organization_name = Column(String, default="")
    accepted = Column(Boolean, nullable=True)
    implemented_intervention = Column(String, default="")
    blueprint_followed = Column(Boolean, nullable=True)
    realized_cost = Column(Float, nullable=True)
    implementation_duration = Column(String, default="")
    measured_result = Column(Text, default="")
    unexpected_constraints = Column(Text, default="")
    would_recommend_same = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
