#!/usr/bin/env python3
"""Run LLM-based extraction on all documents with text, save to DB, and re-export."""

import sys, os, json, uuid, shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import (
    InterventionRecord, MetricRecord, PassageRecord, QualityFlag
)
from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator
from compass_collector.config.settings import EXPORTS_DIR, DATA_DIR
from compass_collector.export.formats import ExportEngine

init_db()
session = get_session()

# --- Backup existing exports ---
backup_dir = EXPORTS_DIR.parent / "exports_backup_pre_llm"
if not backup_dir.exists():
    shutil.copytree(str(EXPORTS_DIR), str(backup_dir))
    print(f"Backed up exports to {backup_dir}")

# --- Clear old intervention records ---
old_inv = session.query(InterventionRecord).delete()
old_metrics = session.query(MetricRecord).delete()
old_passages = session.query(PassageRecord).delete()
old_flags = session.query(QualityFlag).delete()
session.commit()
print(f"Cleared {old_inv} interventions, {old_metrics} metrics, {old_passages} passages, {old_flags} flags")

# --- Run LLM extraction ---
api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
if not api_key:
    print("ERROR: No API key found. Set DEEPSEEK_API_KEY or OPENAI_API_KEY")
    sys.exit(1)

orch = ExtractionOrchestrator()
orch.set_api_key(api_key)

# Load docs with sufficient text
docs = session.query(Document).filter(
    Document.url.startswith("http"),
).all()
doc_list = []
for d in docs:
    text = d.cleaned_text or ""
    if len(text.strip()) < 100:
        if d.title:
            text = d.title
        if len(text.strip()) < 100:
            continue
    doc_list.append({
        "id": d.id,
        "title": d.title or "",
        "url": d.url or "",
        "text": text,
        "source_type": "web",
    })

print(f"Loaded {len(doc_list)} documents with sufficient text")

print("Running relevance filter...")
relevance_results, counts = orch.run_relevance_filter(doc_list)
print(f"  High: {counts['high_relevance']}, Possible: {counts['possible_relevance']}, Not: {counts['not_relevant']}")

relevant_ids = {r["record_id"] for r in relevance_results
                if r["classification"] in ("high_relevance", "possible_relevance")}
relevant_docs = [d for d in doc_list if d["id"] in relevant_ids]
print(f"  Sending {len(relevant_docs)} documents to LLM extraction")

print("Running LLM extraction...")
import time
t0 = time.time()
extractions = []
for i, doc in enumerate(relevant_docs):
    text = doc.get("text", "")
    if not text or len(text.strip()) < 100:
        if doc.get("title"):
            text = doc["title"]
    if not text or len(text.strip()) < 100:
        extractions.append({
            "document_id": doc["id"],
            "title": doc.get("title", "")[:100],
            "url": doc.get("url", ""),
            "extraction": {"has_intervention": False,
                           "extraction_notes": "Insufficient source text"}
        })
        continue
    result = orch.extractor.extract(text, doc.get("title"), doc.get("url"))
    e_result = {
        "document_id": doc["id"],
        "title": doc.get("title", "")[:100],
        "url": doc.get("url", ""),
        "extraction": result,
    }
    extractions.append(e_result)
    with open(orch.output_dir / "extraction_attempts.jsonl", "a") as f:
        f.write(json.dumps(e_result) + "\n")
        f.flush()
    if (i + 1) % 25 == 0:
        elapsed = time.time() - t0
        pct = (i + 1) / len(relevant_docs) * 100
        rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
        cost = orch.extractor.stats['total_cost']
        print(f"  {i+1}/{len(relevant_docs)} ({pct:.0f}%) — {rate:.0f} docs/min — cost: ${cost:.4f}")

print(f"  Completed {len(extractions)} extractions")

# --- Validate ---
print("Validating extractions...")
validation = orch.validate_extractions(extractions)
print(f"  Accepted: {len(validation['accepted'])}, Quarantined: {len(validation['quarantined'])}, Rejected: {len(validation['rejected'])}")

# --- Generate report ---
report = orch.generate_extraction_report(counts, validation, extractions, len(doc_list))
print(report)

# --- Map results to DB ---
print("Mapping extraction results to database...")
accepted_ids = {v["document_id"] for v in validation["accepted"]}
accepted_map = {v["document_id"]: v for v in validation["accepted"]}
extraction_map = {e["document_id"]: e for e in extractions}

for doc in doc_list:
    doc_id = doc["id"]
    e = extraction_map.get(doc_id, {})
    extraction = e.get("extraction", {})
    if not extraction or extraction.get("has_intervention") != True:
        continue
    if doc_id not in accepted_ids:
        continue

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id="",
        document_id=doc_id,
        organization_name=extraction.get("organization_name"),
        organization_anonymized=False,
        organization_industry=extraction.get("organization_industry", []),
        organization_geography=[extraction.get("organization_location")] if extraction.get("organization_location") else [],
        organization_employee_count=extraction.get("organization_size"),
        organization_type=extraction.get("organization_type"),
        problem_business_function=extraction.get("problem_business_function", []),
        problem_statement=extraction.get("problem_statement", ""),
        problem_categories=[],
        intervention_title=extraction.get("intervention_title") or doc.get("title", ""),
        intervention_families=extraction.get("intervention_families", []),
        intervention_description=extraction.get("intervention_description", ""),
        intervention_components=extraction.get("intervention_components", []),
        intervention_software=extraction.get("intervention_software", []),
        intervention_vendors=extraction.get("intervention_vendors", []),
        intervention_teams_involved=extraction.get("intervention_teams_involved", []),
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
        extraction_model=orch.extractor.model,
        extraction_model_version="1.0",
        extracted_at=datetime.utcnow(),
        review_status="pending",
        parser_version="1.0",
        created_at=datetime.utcnow(),
    )
    session.add(record)
    session.flush()

    # Metrics
    for outcome in extraction.get("outcomes", []):
        metric = MetricRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            source_id="",
            metric_name=outcome.get("metric_name", ""),
            metric_category=outcome.get("metric_category", ""),
            baseline_value=outcome.get("baseline_value"),
            post_value=outcome.get("post_value"),
            absolute_change=outcome.get("absolute_change"),
            percentage_change=outcome.get("percentage_change"),
            unit=outcome.get("unit", ""),
            currency=outcome.get("currency"),
            value_type=outcome.get("value_type", "reported"),
            reported_text=outcome.get("source_passage", ""),
        )
        session.add(metric)

    # Passages
    for sp in extraction.get("source_passages", []):
        passage = PassageRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            document_id=doc_id,
            passage_text=sp.get("passage", ""),
            supports_fields=[sp.get("field", "")],
        )
        session.add(passage)

    # Quality flags
    if not extraction.get("organization_name"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_organization"))
    if not extraction.get("implementation_cost"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_implementation_cost"))
    if not extraction.get("has_baseline"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_baseline"))
    if not extraction.get("sample_size"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_sample_size"))
    if extraction.get("is_vendor_reported"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="vendor_reported"))
    if not any(outcome.get("post_value") for outcome in extraction.get("outcomes", [])):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_quantified_outcomes"))

    if (i + 1) % 100 == 0:
        session.commit()
        print(f"  Saved {i+1}/{len(doc_list)} to DB")

session.commit()
print(f"Saved extraction results to DB")

# --- Re-export ---
print("Re-exporting...")
ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
print("Done!")
session.close()
