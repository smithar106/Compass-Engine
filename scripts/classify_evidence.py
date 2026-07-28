#!/usr/bin/env python3
"""Classify unclassified intervention records into evidence tiers.

Classification rules:
  Gold (60+):   Has quantified metrics + baseline/industry/timeline
  Silver (35+): Has metrics plus some supporting data
  Bronze (<35): Minimal data, partial outcomes

Usage:
    python scripts/classify_evidence.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from sqlalchemy import func

session = get_session()

pending = session.query(InterventionRecord).filter(
    (InterventionRecord.review_status == "pending") |
    (InterventionRecord.review_status.is_(None)) |
    (InterventionRecord.review_status == "")
).all()

print(f"Unclassified records: {len(pending)}")

counts = {"gold": 0, "silver": 0, "bronze": 0}
for rec in pending:
    has_metrics = session.query(MetricRecord).filter_by(intervention_id=rec.id).count() > 0
    has_quantified = session.query(MetricRecord).filter_by(intervention_id=rec.id).filter(
        MetricRecord.percentage_change.isnot(None) | MetricRecord.absolute_change.isnot(None)
    ).count() > 0
    score = 0
    score += 25 if has_quantified else 10 if has_metrics else 0
    score += 15 if rec.has_baseline else 0
    score += 10 if rec.intervention_implementation_time_value else 0
    score += 10 if rec.organization_industry and rec.organization_industry not in ("[]", [""]) else 0
    score += 10 if rec.organization_employee_count else 0
    score += 10 if rec.independently_verified else -5 if rec.vendor_reported else 0

    tier = "gold" if score >= 60 else "silver" if score >= 35 else "bronze"
    rec.review_status = tier
    counts[tier] += 1

session.commit()

total = session.query(InterventionRecord).count()
reviews = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
ready = session.query(InterventionRecord.id).filter(
    InterventionRecord.organization_name.isnot(None),
    InterventionRecord.intervention_title != "",
    InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())
).count()

print(f"\nClassified: gold={counts['gold']}, silver={counts['silver']}, bronze={counts['bronze']}")
print(f"Total: {total} | Ready: {ready}")
for t in ["gold", "silver", "bronze"]:
    print(f"  {t}: {reviews.get(t, 0)}")

session.close()
