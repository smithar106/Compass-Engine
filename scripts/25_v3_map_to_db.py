#!/usr/bin/env python3
"""V3: Map ALL tiers to collector_v3.db with source_generation provenance.

Stores Tier 1, 2, and 3 in the DB. Rejected is logged but not stored.
Legacy V1 data is preserved and marked source_generation=v1/v2.
"""

import sys, os, json, uuid, shutil
from datetime import datetime, timezone
from pathlib import Path

V3_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "collector_v3.db"
os.environ["COLLECTOR_DATABASE_URL"] = f"sqlite:///{V3_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import (
    InterventionRecord, MetricRecord, PassageRecord, QualityFlag, DuplicateRelationship
)


def clean_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except:
        return None


def map_tier1(session, e, doc_id, doc, now, generation="v3"):
    """Map a Tier 1 extraction to InterventionRecord."""
    ext = e.get("extraction", {})
    eq = ext.get("evidence_quality") or {}

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id=(ext.get("organization_name") or "")[:100],
        document_id=doc_id,
        organization_name=ext.get("organization_name"),
        organization_anonymized=False,
        organization_industry=ext.get("organization_industry") or [],
        organization_type=ext.get("organization_type"),
        problem_statement=ext.get("business_problem") or "",
        problem_business_function=[ext.get("business_function")] if ext.get("business_function") else [],
        intervention_title=ext.get("intervention_title") or e.get("title", ""),
        intervention_families=ext.get("intervention_subcategories") or [],
        intervention_description=ext.get("intervention_description") or "",
        intervention_software=ext.get("intervention_software") or [],
        intervention_vendors=ext.get("intervention_vendors") or [],
        intervention_teams_involved=ext.get("teams_involved") or [],
        intervention_pilot_used=ext.get("pilot_used"),
        intervention_implementation_cost=clean_num(ext.get("implementation_cost_value")),
        intervention_implementation_cost_currency=ext.get("implementation_cost_currency") or None,
        intervention_implementation_time_value=clean_num(ext.get("implementation_duration_value")),
        intervention_implementation_time_unit=ext.get("implementation_duration_unit"),
        intervention_measurement_period_value=clean_num(ext.get("measurement_period_value")),
        intervention_measurement_period_unit=ext.get("measurement_period_unit"),
        result_status=ext.get("implementation_status") or "unknown",
        success_factors=ext.get("success_factors") or [],
        failure_conditions=ext.get("failure_conditions") or [],
        implementation_challenges=ext.get("challenges") or [],
        risks=[],
        limitations=[],
        unintended_consequences=ext.get("unintended_consequences") or [],
        has_baseline=bool(ext.get("baseline_metrics")),
        has_post_measurement=bool(ext.get("outcomes")),
        has_control_group=eq.get("has_control_group"),
        sample_size=clean_num(eq.get("sample_size")),
        independently_verified=eq.get("independently_verified"),
        vendor_reported=eq.get("is_vendor_reported", False),
        extractor=f"llm_v3",
        extraction_model="deepseek-v4-flash",
        extraction_model_version="3.0",
        extracted_at=now,
        review_status="pending",
        parser_version="3.0",
        created_at=now,
    )
    session.add(record)
    session.flush()

    extra_data = {
        "intervention_category": ext.get("intervention_category"),
        "workflow": ext.get("workflow"),
        "alternatives_considered": ext.get("alternatives_considered"),
        "baseline_description": ext.get("baseline_description"),
        "baseline_metrics": ext.get("baseline_metrics"),
        "result_summary": ext.get("result_summary"),
        "lessons_learned": ext.get("lessons_learned"),
        "evidence_tier": "tier1",
        "source_generation": generation,
        "source_credibility": eq.get("source_credibility"),
        "measurement_method": eq.get("measurement_method"),
    }
    record.intervention_components = extra_data

    for outcome in (ext.get("outcomes") or []):
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

    for sp in (ext.get("source_passages") or []):
        session.add(PassageRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            document_id=doc_id,
            passage_text=sp.get("passage", ""),
            supports_fields=[sp.get("field", "")],
        ))

    if not ext.get("organization_name"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="missing_organization"))
    if not ext.get("outcomes"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_quantified_outcomes"))
    if not ext.get("baseline_metrics"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="no_baseline"))
    if eq.get("is_vendor_reported"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="vendor_reported"))
    if ext.get("implementation_status") in ("abandoned", "failed"):
        session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="failed_implementation"))

    return record


def map_tier2(session, e, doc_id, doc, now, generation="v3"):
    """Map a Tier 2 extraction — leaner record but still stored."""
    ext = e.get("extraction", {})

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id=(ext.get("organization_name") or "tier2_anonymous")[:100],
        document_id=doc_id,
        organization_name=ext.get("organization_name"),
        organization_industry=ext.get("organization_industry") or [],
        organization_type=ext.get("organization_type"),
        problem_statement=ext.get("business_problem") or "",
        problem_business_function=[ext.get("business_function")] if ext.get("business_function") else [],
        intervention_title=ext.get("intervention_title") or e.get("title", ""),
        intervention_families=ext.get("intervention_subcategories") or [],
        intervention_description=(ext.get("outcome_summary") or "")[:2000],
        intervention_software=ext.get("intervention_software") or [],
        intervention_vendors=ext.get("intervention_vendors") or [],
        result_status=ext.get("implementation_status") or "unknown",
        has_baseline=False,
        has_post_measurement=bool(ext.get("outcome_metrics")),
        vendor_reported=(ext.get("evidence_quality") or {}).get("is_vendor_reported", False),
        extractor="llm_v3",
        extraction_model="deepseek-v4-flash",
        extraction_model_version="3.0",
        extracted_at=now,
        review_status="tier2",
        parser_version="3.0",
        created_at=now,
    )
    session.add(record)
    session.flush()

    extra_data = {
        "intervention_category": ext.get("intervention_category"),
        "workflow": ext.get("workflow"),
        "evidence_tier": "tier2",
        "source_generation": generation,
        "missing_attribute": ext.get("missing_attribute"),
        "outcome_summary": ext.get("outcome_summary"),
    }
    record.intervention_components = extra_data

    for m in (ext.get("outcome_metrics") or []):
        session.add(MetricRecord(
            id=str(uuid.uuid4()),
            intervention_id=record.id,
            metric_name=m.get("metric_name", ""),
            metric_category="outcome",
            percentage_change=clean_num(m.get("value")),
            unit=m.get("unit", ""),
            value_type=m.get("value_type", "estimated"),
        ))

    session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="tier2_incomplete"))
    return record


def map_tier3(session, e, doc_id, doc, now, generation="v3"):
    """Map a Tier 3 extraction — supporting evidence, minimal record."""
    ext = e.get("extraction", {})

    record = InterventionRecord(
        id=str(uuid.uuid4()),
        source_id="tier3_supporting",
        document_id=doc_id,
        organization_name=", ".join(ext.get("organizations_mentioned") or [])[:200],
        problem_statement=(ext.get("summary") or "")[:1000],
        intervention_title=(e.get("title") or "")[:500],
        intervention_description=(ext.get("summary") or "")[:2000],
        result_status="supporting",
        has_baseline=False,
        has_post_measurement=False,
        extractor="llm_v3",
        extraction_model="deepseek-v4-flash",
        extraction_model_version="3.0",
        extracted_at=now,
        review_status="tier3",
        parser_version="3.0",
        created_at=now,
    )
    session.add(record)
    session.flush()

    extra_data = {
        "evidence_tier": "tier3",
        "source_generation": generation,
        "evidence_type": ext.get("evidence_type"),
        "organizations_mentioned": ext.get("organizations_mentioned"),
        "workflows_mentioned": ext.get("workflows_mentioned"),
        "source_credibility": ext.get("source_credibility"),
    }
    record.intervention_components = extra_data
    session.add(QualityFlag(id=str(uuid.uuid4()), intervention_id=record.id, flag_name="tier3_supporting_only"))
    return record


def load_v3_extractions(path: Path) -> list:
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    v3_extractions_path = Path(__file__).resolve().parent.parent / "data" / "extraction" / "extraction_v3.jsonl"
    v3_fetched_dir = Path(__file__).resolve().parent.parent / "data" / "v3_fetched"

    extractions = load_v3_extractions(v3_extractions_path)
    if not extractions:
        print("No V3 extractions found. Run 24_v3_extract.py or 30_v3_extract_fetched.py first.")
        print(f"Checked: {v3_extractions_path}")
        sys.exit(1)

    print(f"Loaded {len(extractions)} V3 extractions")

    init_db()
    session = get_session()

    now = datetime.now(timezone.utc)
    counts = {"tier1": 0, "tier2": 0, "tier3": 0, "rejected": 0, "unknown": 0}

    for i, e in enumerate(extractions):
        ext = e.get("extraction", {})
        tier = ext.get("evidence_tier", "unknown")
        doc_id = e.get("document_id", "")

        doc = None
        if doc_id:
            doc = session.query(Document).filter_by(id=doc_id).first()
            if not doc:
                doc_path = v3_fetched_dir / f"{doc_id}.json"
                if doc_path.exists():
                    with open(doc_path) as f:
                        doc_data = json.load(f)
                    doc = Document(
                        id=doc_id,
                        url=doc_data.get("url", ""),
                        title=doc_data.get("title", "")[:500],
                        content_hash=doc_data.get("content_hash", ""),
                        cleaned_text=(doc_data.get("cleaned_text") or "")[:15000],
                        crawl_status="success",
                        document_type="html",
                        parser_version="3.0",
                        created_at=now,
                    )
                    session.add(doc)
                    session.flush()

        if tier == "tier1":
            map_tier1(session, e, doc_id, doc, now, generation="v3")
            counts["tier1"] += 1
        elif tier == "tier2":
            map_tier2(session, e, doc_id, doc, now, generation="v3")
            counts["tier2"] += 1
        elif tier == "tier3":
            map_tier3(session, e, doc_id, doc, now, generation="v3")
            counts["tier3"] += 1
        elif tier == "rejected":
            counts["rejected"] += 1
        else:
            counts["unknown"] += 1

        if (i + 1) % 100 == 0:
            session.commit()
            print(f"  Processed {i+1}/{len(extractions)}")

    session.commit()
    session.close()

    print(f"\n{'='*60}")
    print(f"V3 Mapping complete!")
    print(f"  Tier 1: {counts['tier1']}")
    print(f"  Tier 2: {counts['tier2']}")
    print(f"  Tier 3: {counts['tier3']}")
    print(f"  Rejected (not stored): {counts['rejected']}")
    print(f"  Unknown: {counts['unknown']}")
    print(f"  Database: {V3_DB_PATH}")


if __name__ == "__main__":
    main()
