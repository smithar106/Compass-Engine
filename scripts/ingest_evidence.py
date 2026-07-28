#!/usr/bin/env python3
"""Evidence Ingestion Pipeline

Ingests structured implementation data into the Compass evidence graph.
Reads JSON files from data/seeds/ directory and inserts them into the database.

Usage:
    python scripts/ingest_evidence.py                          # ingest all seed files
    python scripts/ingest_evidence.py --file data/seeds/my_data.json  # specific file
    python scripts/ingest_evidence.py --report                  # just print coverage
"""

import argparse
import json
import uuid
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ingest")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session, init_db
from compass_collector.models.intervention import InterventionRecord, MetricRecord


def generate_id() -> str:
    return str(uuid.uuid4())


def parse_seed_record(record: dict) -> tuple[InterventionRecord, list[MetricRecord]]:
    rec_id = record.get("id") or generate_id()

    intervention = InterventionRecord(
        id=rec_id,
        source_id=record.get("source_id", f"seed-{rec_id[:8]}"),
        organization_name=record.get("organization", ""),
        organization_industry=record.get("industry", None) or [],
        organization_geography=record.get("geography", None) or [],
        organization_employee_count=record.get("employee_count"),
        organization_employee_band=_employee_band(record.get("employee_count")),
        problem_business_function=record.get("business_functions", None) or [],
        problem_statement=record.get("problem", ""),
        problem_categories=record.get("problem_categories", None) or [],
        intervention_title=record.get("intervention", ""),
        intervention_families=record.get("families", None) or [],
        intervention_components=record.get("components", None) or {},
        intervention_description=record.get("description", ""),
        intervention_vendors=record.get("vendors", None) or [],
        intervention_implementation_time_value=record.get("timeline_value"),
        intervention_implementation_time_unit=record.get("timeline_unit", "weeks"),
        intervention_implementation_cost=record.get("implementation_cost"),
        intervention_implementation_cost_currency=record.get("cost_currency", "USD"),
        result_status=record.get("status", "successful"),
        independently_verified=record.get("independently_verified", False),
        vendor_reported=record.get("vendor_reported", False),
        has_baseline=record.get("has_baseline", None),
        has_post_measurement=True,
        extraction_model="seed-v1",
        extractor="ingestion_pipeline",
        extracted_at=datetime.utcnow(),
        review_status=record.get("tier", "tier2"),
        parser_version="3.0.0",
        created_at=datetime.utcnow(),
    )

    metrics = []
    for m in record.get("metrics", []):
        metric = MetricRecord(
            id=generate_id(),
            intervention_id=rec_id,
            source_id=intervention.source_id,
            metric_name=m.get("name", ""),
            metric_category=m.get("category", ""),
            baseline_value=m.get("baseline"),
            post_value=m.get("post"),
            absolute_change=m.get("absolute_change"),
            percentage_change=m.get("percentage_change"),
            unit=m.get("unit", ""),
            currency=m.get("currency"),
            time_period=m.get("time_period", "annual"),
            population_scope=m.get("scope", ""),
            reported_text=m.get("raw_text", ""),
            value_type=m.get("value_type", "reported"),
            created_at=datetime.utcnow(),
        )
        metrics.append(metric)

    return intervention, metrics


def _employee_band(count) -> str | None:
    if count is None:
        return None
    if count < 10:
        return "<10"
    if count < 50:
        return "10-50"
    if count < 200:
        return "50-200"
    if count < 1000:
        return "200-1000"
    if count < 10000:
        return "1000-10000"
    return "10000+"


def ingest_file(filepath: Path, session) -> dict:
    with open(filepath) as f:
        data = json.load(f)

    records = data if isinstance(data, list) else [data]
    stats = {"total": len(records), "inserted": 0, "skipped": 0, "errors": 0, "tiers": {}}

    for record in records:
        try:
            existing = session.query(InterventionRecord).filter_by(
                organization_name=record.get("organization", ""),
                intervention_title=record.get("intervention", ""),
            ).first()
            if existing and not record.get("force", False):
                stats["skipped"] += 1
                continue

            intervention, metrics = parse_seed_record(record)
            session.merge(intervention)
            for m in metrics:
                session.merge(m)

            tier = record.get("tier", "tier2")
            stats["tiers"][tier] = stats["tiers"].get(tier, 0) + 1
            stats["inserted"] += 1

        except Exception as e:
            logger.error(f"Failed to ingest {record.get('organization', 'unknown')}: {e}")
            stats["errors"] += 1

    session.commit()
    return stats


def print_coverage_report(session):
    from sqlalchemy import func

    total = session.query(InterventionRecord).count()
    with_metrics = session.query(MetricRecord.intervention_id).distinct().count()
    reviews = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())

    print("\n" + "=" * 60)
    print("EVIDENCE GRAPH COVERAGE REPORT")
    print("=" * 60)
    print(f"Total implementations:  {total}")
    print(f"With metrics:          {with_metrics}")
    print(f"Recommendation-ready:  {session.query(InterventionRecord.id).filter(InterventionRecord.organization_name.isnot(None), InterventionRecord.intervention_title != '', InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())).count()}")
    print()
    print("By Tier:")
    for t in ["gold", "silver", "bronze"]:
        print(f"  {t}: {reviews.get(t, 0)}")
    print()

    target = 500
    print(f"Target: {target}")
    print(f"Gap:    {max(0, target - total)}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Ingest evidence into Compass")
    parser.add_argument("--file", help="Specific seed file to ingest")
    parser.add_argument("--report", action="store_true", help="Print coverage report only")
    parser.add_argument("--dir", default="data/seeds", help="Seed data directory")
    args = parser.parse_args()

    init_db()
    session = get_session()

    if args.report:
        print_coverage_report(session)
        session.close()
        return

    seed_dir = Path(args.dir)
    if not seed_dir.exists():
        logger.warning(f"Seed directory {seed_dir} does not exist. Creating.")
        seed_dir.mkdir(parents=True, exist_ok=True)

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(seed_dir.glob("*.json"))

    if not files:
        logger.info(f"No seed files found in {seed_dir}")
        print_coverage_report(session)
        session.close()
        return

    total_stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0, "tiers": {}}
    for f in files:
        logger.info(f"Ingesting {f.name}...")
        stats = ingest_file(f, session)
        for k in total_stats:
            if k == "tiers":
                for t, c in stats.get("tiers", {}).items():
                    total_stats["tiers"][t] = total_stats["tiers"].get(t, 0) + c
            else:
                total_stats[k] += stats[k]

    print(f"\nIngestion complete:")
    print(f"  Files:     {len(files)}")
    print(f"  Total:     {total_stats['total']}")
    print(f"  Inserted:  {total_stats['inserted']}")
    print(f"  Skipped:   {total_stats['skipped']}")
    print(f"  Errors:    {total_stats['errors']}")
    print(f"  By tier:   {total_stats['tiers']}")

    print_coverage_report(session)
    session.close()


if __name__ == "__main__":
    main()
