#!/usr/bin/env python3
"""Phase 2: Map extraction_attempts.jsonl results to DB and re-export."""

import sys, os, json, uuid, shutil
from datetime import datetime
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

# Backup exports
backup_dir = EXPORTS_DIR.parent / "exports_backup_pre_llm"
if not backup_dir.exists():
    shutil.copytree(str(EXPORTS_DIR), str(backup_dir))
    print(f"Backed up to {backup_dir}")

# Clear old records
for table in [InterventionRecord, MetricRecord, PassageRecord, QualityFlag]:
    count = session.query(table).delete()
    print(f"Cleared {count} {table.__tablename__}")
session.commit()

# Load extraction results
results_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "extraction" / "extraction_attempts.jsonl"
if not results_path.exists():
    print(f"ERROR: {results_path} not found. Run 07_llm_extraction_only.py first.")
    sys.exit(1)

extractions = []
with open(results_path) as f:
    for line in f:
        line = line.strip()
        if line:
            extractions.append(json.loads(line))

print(f"Loaded {len(extractions)} extraction results")

# Build doc map for source_id
doc_map = {}
created = 0
for i, e in enumerate(extractions):
    extraction = e.get("extraction", {})
    if not extraction.get("has_intervention"):
        continue
    if "_meta" in extraction and "error" in extraction.get("_meta", {}):
        continue

    doc_id = e["document_id"]
    if doc_id not in doc_map:
        doc = session.query(Document).filter_by(id=doc_id).first()
        doc_map[doc_id] = doc

    doc = doc_map.get(doc_id)

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id=doc.source_registry_id if doc else "",
        document_id=doc_id,
        organization_name=extraction.get("organization_name"),
        organization_anonymized=False,
        organization_industry=extraction.get("organization_industry") or [],
        organization_geography=[extraction.get("organization_location")] if extraction.get("organization_location") else [],
        organization_employee_count=_clean_num(extraction.get("organization_size")) if extraction.get("organization_size") and str(extraction.get("organization_size")).isdigit() else None,
        organization_type=extraction.get("organization_type"),
        problem_business_function=extraction.get("problem_business_function") or [],
        problem_statement=extraction.get("problem_statement") or "",
        problem_categories=[],
        intervention_title=extraction.get("intervention_title") or e.get("title", ""),
        intervention_families=extraction.get("intervention_families") or [],
        intervention_description=extraction.get("intervention_description") or "",
        intervention_components=extraction.get("intervention_components") or [],
        intervention_software=extraction.get("intervention_software") or [],
        intervention_vendors=extraction.get("intervention_vendors") or [],
        intervention_teams_involved=extraction.get("intervention_teams_involved") or [],
        intervention_human_review_required=extraction.get("intervention_human_review_required"),
        intervention_pilot_used=extraction.get("intervention_pilot_used"),
        result_status=extraction.get("result_status", "unknown"),
        success_factors=extraction.get("success_factors", []),
        failure_conditions=extraction.get("failure_conditions", []),
        implementation_challenges=extraction.get("implementation_challenges", []),
        risks=extraction.get("risks", []),
        unintended_consequences=extraction.get("unintended_consequences", []),
        has_baseline=False,
        has_control_group=extraction.get("has_control_group"),
        sample_size=extraction.get("sample_size"),
        independently_verified=extraction.get("independently_verified"),
        vendor_reported=extraction.get("is_vendor_reported", False),
        extractor="llm",
        extraction_model=extraction.get("_meta", {}).get("model", "deepseek-v4-flash"),
        extraction_model_version="1.0",
        extracted_at=datetime.utcnow(),
        review_status="pending",
        parser_version="1.0",
        created_at=datetime.utcnow(),
    )
    session.add(record)
    session.flush()

    def _clean_num(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace(",", "").replace("$", "").replace("%", "").replace(" ", "")
        try:
            return float(s)
        except (ValueError, TypeError):
            return None

    for outcome in (extraction.get("outcomes") or []):
        session.add(MetricRecord(
            id=str(uuid.uuid4()), intervention_id=record.id,
            metric_name=outcome.get("metric_name", ""),
            metric_category=outcome.get("metric_category", ""),
            baseline_value=_clean_num(outcome.get("baseline_value")),
            post_value=_clean_num(outcome.get("post_value")),
            absolute_change=_clean_num(outcome.get("absolute_change")),
            percentage_change=_clean_num(outcome.get("percentage_change")),
            unit=outcome.get("unit", ""), currency=outcome.get("currency"),
            value_type=outcome.get("value_type", "reported"),
            reported_text=outcome.get("source_passage", ""),
        ))

    for sp in (extraction.get("source_passages") or []):
        session.add(PassageRecord(
            id=str(uuid.uuid4()), intervention_id=record.id,
            document_id=doc_id,
            passage_text=sp.get("passage", ""),
            supports_fields=[sp.get("field", "")],
        ))

    if not extraction.get("organization_name"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_organization"))
    if not extraction.get("sample_size"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_sample_size"))
    if extraction.get("is_vendor_reported"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="vendor_reported"))
    if not any(o.get("post_value") for o in (extraction.get("outcomes") or [])):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_quantified_outcomes"))

    created += 1
    if created % 100 == 0:
        session.commit()
        print(f"  Saved {created} interventions")

session.commit()
print(f"\nSaved {created} interventions to DB")

print("Re-exporting...")
ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
print("Done!")
session.close()
