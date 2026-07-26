from pydantic import BaseModel, Field
from typing import Optional


class InvestigationRequest(BaseModel):
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
    record_id: str = ""
    organization: str
    industry: str = ""
    geography: str = ""
    organization_size: int = 0
    workflow: str = ""
    intervention: str
    outcome_summary: str = ""
    normalized_metrics: list[dict] = []
    evidence_tier: str = "bronze"
    similarity_score: float = 0
    similarity_dimensions: dict = {}
    source_title: str = ""
    source_url: str = ""
    relevance_explanation: str = ""


class NegativeEvidence(BaseModel):
    organization: str
    intervention: str
    failure_reasons: list[str] = []
    lessons: list[str] = []


class AlternativeConsidered(BaseModel):
    family: str
    reason: str = ""
    confidence_score: float = 0


class EvidenceSummary(BaseModel):
    overall_tier: str = "bronze"
    total_comparables: int = 0
    gold_count: int = 0
    silver_count: int = 0
    bronze_count: int = 0
    status_breakdown: dict = {}
    average_evidence_score: float = 0


class Confidence(BaseModel):
    score: float = 0
    label: str = "insufficient"
    explanation: str = ""


class ImpactEstimate(BaseModel):
    status: str = "insufficient_input"
    low: Optional[float] = None
    expected: Optional[float] = None
    high: Optional[float] = None
    currency: str = "USD"
    basis: str = ""
    confidence: str = "low"


class TimelineEstimate(BaseModel):
    min_weeks: Optional[float] = None
    expected_weeks: Optional[float] = None
    max_weeks: Optional[float] = None
    basis: str = ""


class ProjectTeam(BaseModel):
    min_people: int = 0
    expected_people: int = 0
    max_people: int = 0
    roles: list[str] = []
    basis: str = ""


class ImpactSummary(BaseModel):
    annual_savings: ImpactEstimate = Field(default_factory=ImpactEstimate)
    annual_hours_returned: ImpactEstimate = Field(default_factory=ImpactEstimate)
    implementation_timeline: TimelineEstimate = Field(default_factory=TimelineEstimate)
    project_team: ProjectTeam = Field(default_factory=ProjectTeam)


class Recommendation(BaseModel):
    rank: int
    is_compass_choice: bool = False
    intervention_id: str = ""
    category: str = ""
    title: str
    subtitle: str = ""
    description: str = ""
    selection_status: str = "recommended"
    rationale: str = ""
    why_it_ranked_here: list[str] = []
    assumptions: list[str] = []
    confidence: Confidence
    impact: ImpactSummary = Field(default_factory=ImpactSummary)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    comparable_implementations: list[ComparableEvidence] = []
    risks: list[dict] = []
    alternatives_considered: list[AlternativeConsidered] = []


class RecommendationResponse(BaseModel):
    recommendation_id: str = ""
    status: str = "complete"
    engine_version: str = "3.0.0"
    dataset_version: str = "v3"
    generated_at: str = ""
    assessment_summary: dict = {}
    impact_summary: ImpactSummary = Field(default_factory=ImpactSummary)
    recommendations: list[Recommendation] = []
    risks: list[dict] = []
    methodology: dict = {}
