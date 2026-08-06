from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, Float, Integer, JSON
from compass_collector.database import Base


class InterventionRecord(Base):
    __tablename__ = "intervention_records"

    id = Column(String, primary_key=True)
    source_id = Column(String, index=True)
    document_id = Column(String, index=True)

    organization_name = Column(String, nullable=True)
    organization_anonymized = Column(Boolean, default=False)
    organization_industry = Column(JSON, default=list)
    organization_geography = Column(JSON, default=list)
    organization_employee_count = Column(Integer, nullable=True)
    organization_employee_band = Column(String, nullable=True)
    organization_revenue = Column(Float, nullable=True)
    organization_revenue_band = Column(String, nullable=True)
    organization_stage = Column(String, nullable=True)
    organization_type = Column(String, nullable=True)

    # Canonical organization normalization (Phase 3 backfill). JSON of
    # {field: {raw, value, source, method, confidence, version}}.
    organization_normalized = Column(JSON, default=dict)

    problem_business_function = Column(JSON, default=list)
    problem_statement = Column(Text, default="")
    problem_categories = Column(JSON, default=list)
    problem_root_causes = Column(JSON, default=list)
    problem_baseline_description = Column(Text, default="")

    intervention_title = Column(String, default="")
    intervention_families = Column(JSON, default=list)
    intervention_description = Column(Text, default="")
    intervention_components = Column(JSON, default=list)
    intervention_software = Column(JSON, default=list)
    intervention_vendors = Column(JSON, default=list)
    # Canonical knowledge layer (Phase 4): raw values preserved in the
    # columns above; normalized values + provenance stored alongside.
    # JSON: {raw_value: {raw, value, label, source, method, confidence, version}}
    intervention_vendors_normalized = Column(JSON, default=dict)
    intervention_software_normalized = Column(JSON, default=dict)
    intervention_teams_involved = Column(JSON, default=list)
    intervention_human_review_required = Column(Boolean, nullable=True)
    intervention_pilot_used = Column(Boolean, nullable=True)
    intervention_implementation_cost = Column(Float, nullable=True)
    intervention_implementation_cost_currency = Column(String, nullable=True)
    intervention_implementation_time_value = Column(Float, nullable=True)
    intervention_implementation_time_unit = Column(String, nullable=True)
    intervention_measurement_period_value = Column(Float, nullable=True)
    intervention_measurement_period_unit = Column(String, nullable=True)

    result_status = Column(String, default="unknown")
    success_factors = Column(JSON, default=list)
    failure_conditions = Column(JSON, default=list)
    implementation_challenges = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    limitations = Column(JSON, default=list)
    unintended_consequences = Column(JSON, default=list)

    has_baseline = Column(Boolean, nullable=True)
    has_post_measurement = Column(Boolean, nullable=True)
    has_control_group = Column(Boolean, nullable=True)
    sample_size = Column(Integer, nullable=True)
    measurement_method = Column(String, nullable=True)
    independently_verified = Column(Boolean, nullable=True)
    vendor_reported = Column(Boolean, nullable=True)

    extractor = Column(String, default="")
    extraction_model = Column(String, default="")
    extraction_model_version = Column(String, default="")
    extracted_at = Column(DateTime, default=datetime.utcnow)
    review_status = Column(String, default="pending")
    parser_version = Column(String, default="1.0")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Provenance-based evidence model
    implementation_provenance = Column(String, nullable=True)
    outcome_provenance = Column(String, nullable=True)
    implementation_detail_score = Column(Integer, nullable=True)
    outcome_credibility_score = Column(Integer, nullable=True)
    methodology_detail_score = Column(Integer, nullable=True)
    operational_insight_score = Column(Integer, nullable=True)
    outcome_block = Column(JSON, default=dict)
    source_type = Column(String, nullable=True)
    evidence_level = Column(String, nullable=True)

    # Implementation decision-support fields
    implementation_partner = Column(JSON, default=list)
    implementation_pattern = Column(JSON, default=list)
    lessons_learned = Column(JSON, default=list)
    change_management = Column(Text, default="")
    rollout_strategy = Column(Text, default="")
    governance_model = Column(Text, default="")

    # Implementation Intelligence fields — how the implementation actually happened
    executive_sponsor = Column(String, nullable=True)
    pilot_structure = Column(Text, default="")
    training_approach = Column(Text, default="")
    adoption_approach = Column(Text, default="")
    implementation_team_structure = Column(Text, default="")
    budget_range = Column(String, nullable=True)
    key_decision_makers = Column(JSON, default=list)
    success_criteria = Column(JSON, default=list)

    # Per-field provenance trace — for every extracted implementation field,
    # records: value, supporting_text, source_id, source_url, source_section,
    # extraction_confidence, explicit_vs_inferred
    implementation_field_provenance = Column(JSON, default=list)

    # Implementation density classification
    # rich: 4+ populated fields, usable: 2-3, thin: 0-1
    implementation_richness = Column(String, nullable=True)


class MetricRecord(Base):
    __tablename__ = "metric_records"

    id = Column(String, primary_key=True)
    intervention_id = Column(String, index=True)
    source_id = Column(String, index=True)

    metric_name = Column(String, nullable=False)
    metric_category = Column(String, default="")
    baseline_value = Column(Float, nullable=True)
    post_value = Column(Float, nullable=True)
    absolute_change = Column(Float, nullable=True)
    percentage_change = Column(Float, nullable=True)
    unit = Column(String, default="")
    currency = Column(String, nullable=True)
    time_period = Column(String, nullable=True)
    population_scope = Column(String, nullable=True)
    reported_text = Column(Text, default="")
    value_type = Column(String, default="reported")
    calculation_formula = Column(String, nullable=True)
    calculation_inputs = Column(JSON, default=list)
    ambiguity_flags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class PassageRecord(Base):
    __tablename__ = "passage_records"

    id = Column(String, primary_key=True)
    source_id = Column(String, index=True)
    intervention_id = Column(String, index=True)
    document_id = Column(String, index=True)

    page_number = Column(Integer, nullable=True)
    section = Column(String, nullable=True)
    passage_text = Column(Text, default="")
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    table_name = Column(String, nullable=True)
    figure_name = Column(String, nullable=True)
    supports_fields = Column(JSON, default=list)
    extraction_confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)


class QualityFlag(Base):
    __tablename__ = "quality_flags"

    id = Column(String, primary_key=True)
    intervention_id = Column(String, index=True)
    record_type = Column(String, default="intervention")
    flag_name = Column(String, nullable=False)
    flag_category = Column(String, default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class DuplicateRelationship(Base):
    __tablename__ = "duplicate_relationships"

    id = Column(String, primary_key=True)
    source_a_id = Column(String, nullable=False, index=True)
    source_b_id = Column(String, nullable=False, index=True)
    relationship_type = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
