from pydantic import BaseModel, Field
from typing import Optional


class InvestigationRequest(BaseModel):
    investigation_id: Optional[str] = None
    business_function: str = ""
    workflow: str = ""
    problem_statement: str = ""
    industry: str = ""
    company_size: str = ""
    workflow_frequency: str = ""
    people_involved: str = ""
    handoffs: str = ""
    current_tools: list[str] = []
    exception_rate: str = ""
    budget_range: str = ""
    implementation_timeline: str = ""
    business_risk: str = ""
    process_stability: str = ""
    previous_attempts: str = ""
    desired_outcome: str = ""


class ComparableEvidence(BaseModel):
    organization: str
    industry: str = ""
    workflow: str = ""
    intervention: str
    outcome: str
    status: str = "unknown"
    similarity_score: float = 0
    evidence_score: float = 0
    evidence_tier: str = "bronze"
    supporting_passage: str = ""
    source_title: str = ""
    source_url: str = ""


class NegativeEvidence(BaseModel):
    organization: str
    intervention: str
    failure_reasons: list[str] = []
    similarity_score: float = 0


class AlternativeConsidered(BaseModel):
    family: str
    reason: str = ""


class EvidenceSummary(BaseModel):
    overall_tier: str = "bronze"
    total_comparables: int = 0
    gold_count: int = 0
    silver_count: int = 0
    bronze_count: int = 0
    failed_comparables: int = 0
    average_evidence_score: float = 0


class Confidence(BaseModel):
    score: float = 0
    label: str = "limited"
    explanation: str = ""


class ProjectedImpact(BaseModel):
    label: str = ""
    low: Optional[float] = None
    high: Optional[float] = None
    unit: str = ""
    methodology: str = ""
    is_sufficiently_supported: bool = False


class Timeline(BaseModel):
    low_weeks: Optional[float] = None
    high_weeks: Optional[float] = None


class Recommendation(BaseModel):
    rank: int
    is_compass_choice: bool = False
    title: str
    summary: str
    intervention_category: str
    fit_score: float = 0
    confidence: Confidence
    evidence_summary: EvidenceSummary
    projected_impact: ProjectedImpact
    timeline: Timeline
    why_it_ranked: list[str] = []
    comparables: list[ComparableEvidence] = []
    negative_evidence: list[NegativeEvidence] = []
    alternatives_considered: list[AlternativeConsidered] = []
    assumptions: list[str] = []
    risks: list[dict] = []
    annual_savings: Optional[dict] = None
    hours_returned: Optional[dict] = None
    tools: list[str] = []
    subtitle: str = ""


class RecommendationResponse(BaseModel):
    recommendation_run_id: str = ""
    problem_profile: dict = {}
    recommendations: list[Recommendation] = []
    confidence_breakdown: dict = {}
