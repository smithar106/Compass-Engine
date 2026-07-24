#!/usr/bin/env python3
"""Map extraction_v2.jsonl results to DB using the new Tier 1 schema."""

import sys, os, json, uuid, shutil
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import (
    InterventionRecord, MetricRecord, PassageRecord, QualityFlag
)
from compass_collector.config.settings import EXPORTS_DIR
from compass_collector.export.formats import ExportEngine

init_db()
session = get_session()

# Backup current exports
backup_dir = EXPORTS_DIR.parent / "exports_backup_v2"
if not backup_dir.exists():
    shutil.copytree(str(EXPORTS_DIR), str(backup_dir))
    print(f"Backed up to {backup_dir}")

# Clear old records
for table in [InterventionRecord, MetricRecord, PassageRecord, QualityFlag]:
    count = session.query(table).delete()
    print(f"Cleared {count} {table.__tablename__}")
session.commit()

# Load extraction results
results_path = Path(__file__).resolve().parent.parent / "data" / "extraction" / "extraction_v2.jsonl"
if not results_path.exists():
    print(f"ERROR: {results_path} not found")
    sys.exit(1)

extractions = []
with open(results_path) as f:
    for line in f:
        line = line.strip()
        if line:
            extractions.append(json.loads(line))

print(f"Loaded {len(extractions)} extraction results")

# Count tiers
tiers = {}
for e in extractions:
    t = e.get("extraction", {}).get("evidence_tier", "unknown")
    tiers[t] = tiers.get(t, 0) + 1
print(f"Tiers: {json.dumps(tiers)}")

def clean_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

now = datetime.now(timezone.UTC)
doc_cache = {}
created = 0

for i, e in enumerate(extractions):
    extraction = e.get("extraction", {})
    if extraction.get("evidence_tier") != "tier1":
        continue

    doc_id = e["document_id"]
    if doc_id not in doc_cache:
        doc_cache[doc_id] = session.query(Document).filter_by(id=doc_id).first()
    doc = doc_cache[doc_id]

    eq = extraction.get("evidence_quality") or {}

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id=doc.source_registry_id if doc else "",
        document_id=doc_id,
        organization_name=extraction.get("organization_name"),
        organization_anonymized=False,
        organization_industry=extraction.get("organization_industry") or [],
        organization_employee_count=clean_num(extraction.get("organization_employee_count")),
        organization_type=extraction.get("organization_type"),
        problem_statement=extraction.get("business_problem") or "",
        problem_business_function=[extraction.get("business_function")] if extraction.get("business_function") else [],
        intervention_title=extraction.get("intervention_title") or e.get("title", ""),
        intervention_families=extraction.get("intervention_subcategories") or [],
        intervention_description=extraction.get("intervention_description") or "",
        intervention_software=extraction.get("intervention_software") or [],
        intervention_vendors=extraction.get("intervention_vendors") or [],
        intervention_teams_involved=extraction.get("teams_involved") or [],
        intervention_pilot_used=extraction.get("pilot_used"),
        intervention_implementation_cost=clean_num(extraction.get("implementation_cost_value")),
        intervention_implementation_cost_currency=extraction.get("implementation_cost_currency"),
        intervention_implementation_time_value=clean_num(extraction.get("implementation_duration_value")),
        intervention_implementation_time_unit=extraction.get("implementation_duration_unit"),
        intervention_measurement_period_value=clean_num(extraction.get("measurement_period_value")),
        intervention_measurement_period_unit=extraction.get("measurement_period_unit"),
        result_status=extraction.get("implementation_status", "unknown"),
        success_factors=extraction.get("success_factors") or [],
        failure_conditions=extraction.get("failure_conditions") or [],
        implementation_challenges=extraction.get("challenges") or [],
        risks=[],
        limitations=[],
        unintended_consequences=extraction.get("unintended_consequences") or [],
        has_baseline=bool(extraction.get("baseline_metrics")),
        has_control_group=eq.get("has_control_group"),
        sample_size=clean_num(eq.get("sample_size")),
        independently_verified=eq.get("independently_verified"),
        vendor_reported=eq.get("is_vendor_reported", False),
        extractor="llm_v2",
        extraction_model="deepseek-v4-flash",
        extraction_model_version="2.0",
        extracted_at=now,
        review_status="pending",
        parser_version="2.0",
        created_at=now,
    )
    session.add(record)
    session.flush()

    # Store extra data (intervention_category, workflow, baseline_description, etc.) in a JSON metadata column
    # We can use intervention_components for now (it's a JSON field)
    extra_data = {
        "intervention_category": extraction.get("intervention_category"),
        "workflow": extraction.get("workflow"),
        "alternatives_considered": extraction.get("alternatives_considered"),
        "baseline_description": extraction.get("baseline_description"),
        "baseline_metrics": extraction.get("baseline_metrics"),
        "result_summary": extraction.get("result_summary"),
        "lessons_learned": extraction.get("lessons_learned"),
        "implementation_status": extraction.get("implementation_status"),
        "implementation_start_date": extraction.get("implementation_start_date"),
        "evidence_tier": "tier1",
        "source_credibility": eq.get("source_credibility"),
        "measurement_method": eq.get("measurement_method"),
    }
    record.intervention_components = extra_data

    # Metrics
    for outcome in (extraction.get("outcomes") or []):
        session.add(MetricRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            metric_name=outcome.get("metric_name", ""),
            metric_category=outcome.get("category", ""),
            baseline_value=clean_num(outcome.get("baseline_value")),
            post_value=clean_num(outcome.get("post_value")),
            absolute_change=clean_num(outcome.get("absolute_change")),
            percentage_change=clean_num(outcome.get("percentage_change")),
            unit=outcome.get("unit", ""),
            value_type=outcome.get("value_type", "reported"),
            reported_text=outcome.get("source_passage", ""),
        ))

    # Passages
    for sp in (extraction.get("source_passages") or []):
        session.add(PassageRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            document_id=doc_id,
            passage_text=sp.get("passage", ""),
            supports_fields=[sp.get("field", "")],
        ))

    # Quality flags
    if not extraction.get("organization_name"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_organization"))
    if not extraction.get("outcomes"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_quantified_outcomes"))
    if not extraction.get("baseline_metrics"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_baseline"))
    if eq.get("is_vendor_reported"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="vendor_reported"))
    if extraction.get("implementation_status") in ("abandoned", "failed"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="failed_implementation"))
    if not extraction.get("implementation_cost_value"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_cost"))

    created += 1
    if created % 50 == 0:
        session.commit()
        print(f"  Saved {created} interventions")

session.commit()
print(f"\nSaved {created} Tier 1 interventions to DB")

# Re-export
ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
print("Done! Check data/exports/")
session.close()
