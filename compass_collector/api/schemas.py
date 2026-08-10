from pydantic import BaseModel, Field
from typing import Optional


class InvestigationRequest(BaseModel):
    business_function: str = ""
    workflow: str = ""
    problem_statement: str = ""
    constraint: str = ""  # capacity, errors, speed, quality, cost, visibility, compliance, unknown
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
    geography: str = ""
    constraints: list[str] = []
    implementation_capacity: str = ""
    standardization_level: str = ""  # repeatable, with_exceptions, variable, heavy_judgment
    failure_impact: str = ""  # low, moderate, material, regulatory
    # Organization-specific impact inputs (collected by the assessment).
    annual_workflow_volume: str = ""
    current_handling_time: str = ""
    loaded_labor_cost: str = ""


class ScoreComponent(BaseModel):
    score: float = 0.0
    weight: float = 0.0
    reason: str = ""


class ScoreBreakdown(BaseModel):
    problem_alignment: ScoreComponent = Field(default_factory=ScoreComponent)
    organizational_similarity: ScoreComponent = Field(default_factory=ScoreComponent)
    goal_alignment: ScoreComponent = Field(default_factory=ScoreComponent)
    evidence_strength: ScoreComponent = Field(default_factory=ScoreComponent)
    implementation_fit: ScoreComponent = Field(default_factory=ScoreComponent)
    outcome_consistency: ScoreComponent = Field(default_factory=ScoreComponent)


class ComparableImplementationComparison(BaseModel):
    organization_name: str = ""
    organization_type: str = ""
    company_size_category: str = ""
    industry: str = ""
    problem_addressed: str = ""
    intervention_used: str = ""
    documented_outcome: str = ""
    metric: str = ""
    evidence_quality_score: float = 0.0
    source_citation: str = ""
    comparability_explanation: str = ""


class ScoredInterventionResult(BaseModel):
    intervention_id: str = ""
    intervention_name: str = ""
    rank: int = 0
    label: str = "alternative"
    match_score: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    expected_impact: str = ""
    evidence_strength: str = ""
    implementation_difficulty: str = ""
    estimated_timeframe: str = ""
    top_risks: list[str] = []
    key_advantages: list[str] = []
    key_tradeoffs: list[str] = []
    comparable_implementations: list[ComparableImplementationComparison] = []
    rationale: str = ""


class InterventionSelectionRequest(BaseModel):
    recommendation_id: str = ""
    selected_intervention_id: str = ""


class InterventionSelectionResponse(BaseModel):
    selection_id: str = ""
    recommendation_id: str = ""
    selected_intervention_id: str = ""
    selected_intervention_name: str = ""
    recommendation_version: str = ""
    scoring_config_version: str = ""
    scoring_weights: dict = {}
    user_inputs_snapshot: dict = {}
    score_breakdown_snapshot: dict = {}
    evidence_ids_used: list[str] = []
    selection_timestamp: str = ""
    status: str = "active"


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
    decision_relevance: str = "supporting"  # direct | supporting | rejected
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
    decision_grade_count: int = 0
    supporting_count: int = 0
    directly_comparable: bool = True
    compatibility_notes: str = ""
    calculation_method: str = "median_minmax"
    source_record_ids: list[str] = []


class WhyRankedFirst(BaseModel):
    summary: str = ""
    supporting_reasons: list[str] = []
    tradeoffs: list[str] = []
    alternative_differences: list[dict] = []


class TraceFactor(BaseModel):
    factor: str = ""
    raw: float = 0.0
    weighted: float = 0.0


class RecommendationTrace(BaseModel):
    """Internal defensibility trace for a recommendation (retained, not
    necessarily shown in the customer UI)."""
    primary_reasons: list[TraceFactor] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)          # gold/silver/mixed counts
    primary_uncertainty: str = ""
    comparable_count: int = 0


class Counterevidence(BaseModel):
    """Evidence AGAINST the leading recommendation — differentiates Compass
    from software that only rationalizes its top pick."""
    organization: str = ""
    intervention: str = ""
    reason: str = ""


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
    overall_tier: str = "supporting"
    total_comparables: int = 0
    gold_count: int = 0
    decision_grade_count: int = 0
    supporting_count: int = 0
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
    trace: Optional[RecommendationTrace] = None
    counterevidence: list[Counterevidence] = Field(default_factory=list)
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
    scored_interventions: list[ScoredInterventionResult] = []
    risks: list[dict] = []
    methodology: dict = {}
    methodology_summary: str = ""
    assumptions: list[Assumption] = []
    information_gaps: list[InformationGap] = []
    next_validation_steps: list[NextValidationStep] = []
    scoring_config_version: str = ""
    scoring_weights_used: dict = {}
    evidence_graph_timestamp: str = ""
