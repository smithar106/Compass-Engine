"""Pydantic models for the Compass Evidence Graph ingestion pipeline.

These models are independent of the existing SQLAlchemy ORM models.
They define the structured schema for evidence extraction, validation,
and Neo4j persistence.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    HTML = "html"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    MARKDOWN = "markdown"
    TEXT = "text"
    UNKNOWN = "unknown"


class InterventionType(str, Enum):
    WORKFLOW_AUTOMATION = "workflow_automation"
    AI = "ai"
    SOFTWARE = "software"
    PROCESS_REDESIGN = "process_redesign"
    STAFFING = "staffing"
    HYBRID = "hybrid"
    OUTSOURCING = "outsourcing"
    SHARED_SERVICES = "shared_services"
    POLICY_CHANGE = "policy_change"
    TRAINING = "training"
    NO_INTERVENTION = "no_intervention"
    UNKNOWN = "unknown"


class OutcomeDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class MetricCategory(str, Enum):
    TIME = "time"
    COST = "cost"
    REVENUE = "revenue"
    QUALITY = "quality"
    SATISFACTION = "satisfaction"
    ADOPTION = "adoption"
    EFFICIENCY = "efficiency"
    PRODUCTIVITY = "productivity"
    ENGAGEMENT = "engagement"
    RISK = "risk"
    OTHER = "other"


class EvidenceRelationship(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    REPLICATES = "REPLICATES"
    EXTENDS = "EXTENDS"
    DUPLICATES = "DUPLICATES"
    UNRELATED = "UNRELATED"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    AUTO_APPROVED = "auto_approved"


class ClaimType(str, Enum):
    PROBLEM = "problem"
    INTERVENTION = "intervention"
    IMPLEMENTATION = "implementation"
    OUTCOME = "outcome"
    ORGANIZATION = "organization"
    METRIC = "metric"
    RISK = "risk"
    LESSON = "lesson"


# ---------------------------------------------------------------------------
# Source locator — every claim must point back to a specific location
# ---------------------------------------------------------------------------

class SourceLocator(BaseModel):
    """Points to the exact location of a claim in its source document."""
    page: Optional[int] = None
    section: Optional[str] = None
    paragraph: Optional[int] = None
    table_index: Optional[int] = None
    text_excerpt: str = Field(..., description="Short supporting quote from the source")


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class Section(BaseModel):
    section_id: str = ""
    heading: str = ""
    page: Optional[int] = None
    text: str = ""
    tables: List[Dict[str, Any]] = []


class InputDocument(BaseModel):
    """Normalized document after parsing."""
    document_id: str = ""
    source_url: str = ""
    canonical_url: str = ""
    title: str = ""
    publisher: str = ""
    authors: List[str] = []
    publication_date: Optional[str] = None
    document_type: DocumentType = DocumentType.UNKNOWN
    content_hash: str = ""
    language: str = "en"
    sections: List[Section] = []
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Evidence entities
# ---------------------------------------------------------------------------

class Problem(BaseModel):
    name: str = ""
    normalized_name: str = ""
    description: str = ""
    industry: List[str] = []
    business_function: List[str] = []
    root_causes: List[str] = []
    symptoms: List[str] = []


class Intervention(BaseModel):
    name: str = ""
    normalized_name: str = ""
    description: str = ""
    intervention_type: InterventionType = InterventionType.UNKNOWN
    technologies_used: List[str] = []
    process_changes: List[str] = []
    vendors: List[str] = []
    implementation_requirements: List[str] = []
    risks: List[str] = []


class Organization(BaseModel):
    name: str = ""
    normalized_name: str = ""
    organization_type: str = ""
    industry: List[str] = []
    geography: List[str] = []
    employee_count: Optional[int] = None
    revenue: Optional[float] = None
    operating_context: str = ""


class Implementation(BaseModel):
    intervention: Intervention = Field(default_factory=Intervention)
    organization: Organization = Field(default_factory=Organization)
    problem_addressed: str = ""
    start_date: Optional[str] = None
    duration_value: Optional[float] = None
    duration_unit: str = ""
    scope: str = ""
    systems_involved: List[str] = []
    implementation_steps: List[str] = []
    cost_value: Optional[float] = None
    cost_currency: str = "USD"
    staffing_requirements: List[str] = []


class Metric(BaseModel):
    name: str = ""
    category: MetricCategory = MetricCategory.OTHER
    baseline_value: Optional[float] = None
    post_value: Optional[float] = None
    absolute_change: Optional[float] = None
    percentage_change: Optional[float] = None
    unit: str = ""
    direction: OutcomeDirection = OutcomeDirection.NEUTRAL
    value_type: str = "observed"  # observed, projected, estimated
    source_passage: str = ""


class Outcome(BaseModel):
    metric: Metric = Field(default_factory=Metric)
    summary: str = ""
    timeframe: str = ""
    qualitative_description: str = ""
    limitations: List[str] = []


class EvidenceQuality(BaseModel):
    source_credibility: str = "medium"  # high/medium/low
    methodology_quality: Optional[str] = None
    sample_size: Optional[int] = None
    has_control_group: Optional[bool] = None
    is_independent: bool = False
    is_vendor_reported: bool = True
    has_baseline: bool = False
    recency_years: Optional[int] = None
    extraction_confidence: float = 0.0

    def overall_score(self) -> float:
        score = 0.0
        score += 0.25 if self.is_independent else 0.1
        score += 0.2 if self.has_baseline else 0.0
        score += 0.15 if self.sample_size and self.sample_size >= 30 else 0.05
        score += 0.15 if self.has_control_group else 0.0
        score += 0.15 if not self.is_vendor_reported else 0.05
        score += 0.1 if self.recency_years and self.recency_years <= 3 else 0.0
        return round(min(1.0, score), 2)


class EvidenceClaim(BaseModel):
    """A single extracted claim with full provenance."""
    claim_id: str = ""
    claim_type: ClaimType = ClaimType.PROBLEM
    claim_text: str = ""
    problem: Problem = Field(default_factory=Problem)
    intervention: Intervention = Field(default_factory=Intervention)
    organization: Organization = Field(default_factory=Organization)
    implementation: Implementation = Field(default_factory=Implementation)
    outcome: Outcome = Field(default_factory=Outcome)
    metrics: List[Metric] = []
    source_document_id: str = ""
    source_url: str = ""
    source_locator: SourceLocator = Field(default_factory=SourceLocator)
    supporting_excerpt: str = ""
    extraction_confidence: float = 0.0
    evidence_quality: EvidenceQuality = Field(default_factory=EvidenceQuality)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    created_at: str = ""


# ---------------------------------------------------------------------------
# Normalized entity (for alias resolution)
# ---------------------------------------------------------------------------

class NormalizedEntity(BaseModel):
    canonical_name: str = ""
    aliases: List[str] = []
    entity_type: str = ""  # organization, intervention, problem, technology
    normalization_confidence: float = 0.0
    merge_history: List[str] = []


# ---------------------------------------------------------------------------
# Ingestion run (observability)
# ---------------------------------------------------------------------------

class IngestionRun(BaseModel):
    run_id: str = ""
    started_at: str = ""
    completed_at: Optional[str] = None
    status: str = "running"  # running, completed, failed
    sources_discovered: int = 0
    documents_downloaded: int = 0
    documents_parsed: int = 0
    parsing_failures: int = 0
    extraction_failures: int = 0
    claims_created: int = 0
    duplicates_detected: int = 0
    contradictions_detected: int = 0
    graph_nodes_created: int = 0
    graph_nodes_updated: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    errors: List[str] = []


# ---------------------------------------------------------------------------
# Extraction result (output of LLM extraction step)
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    document_id: str = ""
    claims: List[EvidenceClaim] = []
    raw_llm_output: str = ""
    extraction_model: str = ""
    prompt_version: str = ""
    token_usage: int = 0
    cost: float = 0.0
    errors: List[str] = []


# ---------------------------------------------------------------------------
# Evidence relationship (supports/contradicts between claims)
# ---------------------------------------------------------------------------

class EvidenceRelationshipRecord(BaseModel):
    source_claim_id: str = ""
    target_claim_id: str = ""
    relationship: EvidenceRelationship = EvidenceRelationship.UNRELATED
    confidence: float = 0.0
    rationale: str = ""
