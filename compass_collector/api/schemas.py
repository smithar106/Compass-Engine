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
    organization_size: Optional[int] = 0
    workflow: str = ""
    problem: str = ""
    workflow_context: str = ""
    intervention: str
    intervention_category: str = ""
    intervention_description: str = ""
    implementation_status: str = ""
    observed_outcome: str = ""
    outcome_summary: str = ""
    normalized_metrics: list[dict] = []
    evidence_tier: str = "bronze"
    evidence_score: float = 0
    similarity_score: float = 0
    similarity_dimensions: dict = {}
    relevance_explanation: str = ""
    limitations: str = ""
    source_title: str = ""
    source_url: str = ""
    publication_date: str = ""


class NegativeEvidence(BaseModel):
    organization: str
    intervention: str
    failure_reasons: list[str] = []
    lessons: list[str] = []


class OutcomeRange(BaseModel):
    metric_key: str = ""
    metric_label: str = ""
    metric_category: str = ""
    unit: str = ""
    direction: str = ""
    low: Optional[float] = None
    median: Optional[float] = None
    high: Optional[float] = None
    sample_size: int = 0
    gold_count: int = 0
    silver_count: int = 0
    bronze_count: int = 0
    directly_comparable: bool = True
    compatibility_notes: str = ""
    calculation_method: str = "median_minmax"
    source_record_ids: list[str] = []


class WhyRankedFirst(BaseModel):
    summary: str = ""
    supporting_reasons: list[str] = []
    tradeoffs: list[str] = []
    alternative_differences: list[dict] = []


class AlternativeComparison(BaseModel):
    category: str = ""
    specific_intervention: str = ""
    rank: int = 0
    evidence_strength: str = ""
    outcome_support: str = ""
    data_requirements: str = ""
    implementation_complexity: str = ""
    expected_timeline: str = ""
    team_requirements: str = ""
    time_to_value: str = ""
    primary_advantages: list[str] = []
    primary_limitations: list[str] = []
    reason_for_rank: str = ""


class Assumption(BaseModel):
    title: str = ""
    explanation: str = ""
    effect_on_recommendation: str = ""
    effect_on_confidence: str = ""
    resolution_action: str = ""


class InformationGap(BaseModel):
    title: str = ""
    explanation: str = ""
    effect_on_recommendation: str = ""
    effect_on_confidence: str = ""
    resolution_action: str = ""


class NextValidationStep(BaseModel):
    action: str = ""
    purpose: str = ""
    owner: str = ""
    duration: str = ""
    required_inputs: list[str] = []
    success_criteria: str = ""
    decision_enabled: str = ""


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
    missing_inputs: list[str] = []
    what_can_be_reported: str = ""
    prompt_for_user: str = ""


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


class AlternativeConsidered(BaseModel):
    family: str
    reason: str = ""
    confidence_score: float = 0


class SpecificIntervention(BaseModel):
    title: str = ""
    description: str = ""
    required_changes: list[str] = []
    scope_boundaries: list[str] = []
    prerequisites: list[str] = []
    excluded_scope: list[str] = []


class Recommendation(BaseModel):
    rank: int
    is_compass_choice: bool = False
    intervention_id: str = ""
    category: str = ""
    title: str
    specific_action: str = ""
    specific_intervention: SpecificIntervention = Field(default_factory=SpecificIntervention)
    subtitle: str = ""
    description: str = ""
    selection_status: str = "recommended"
    rationale: str = ""
    why_it_ranked_here: list[str] = []
    assumptions: list[str] = []
    confidence: Confidence
    impact: ImpactSummary = Field(default_factory=ImpactSummary)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    outcome_ranges: list[OutcomeRange] = []
    why_ranked_first: Optional[WhyRankedFirst] = None
    alternative_comparison: Optional[AlternativeComparison] = None
    comparable_implementations: list[ComparableEvidence] = []
    risks: list[dict] = []
    alternatives_considered: list[AlternativeConsidered] = []
    assumptions_detail: list[Assumption] = []
    information_gaps: list[InformationGap] = []
    next_validation_step: Optional[NextValidationStep] = None


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
    methodology_summary: str = ""
    assumptions: list[Assumption] = []
    information_gaps: list[InformationGap] = []
    next_validation_steps: list[NextValidationStep] = []
