#!/usr/bin/env python3
"""Evidence Graph Analytics Report — CLI dashboard for database quality and coverage.

Usage:
    ./venv/bin/python scripts/evidence_analytics.py
    ./venv/bin/python scripts/evidence_analytics.py --json   # machine-readable
"""

import json, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.models.document import Document
from sqlalchemy import func


def collect_stats(session) -> dict:
    total_docs = session.query(Document).count()
    fetched = session.query(Document).filter(Document.crawl_status == "success").count()
    failed = session.query(Document).filter(Document.crawl_status == "failed").count()
    parsed = session.query(Document).filter(Document.cleaned_text.isnot(None)).count()

    total_recs = session.query(InterventionRecord).count()
    with_metrics = session.query(MetricRecord.intervention_id).distinct().count()
    quantified = session.query(MetricRecord.intervention_id).filter(
        MetricRecord.percentage_change.isnot(None) | MetricRecord.absolute_change.isnot(None)
    ).distinct().count()

    # Recommendation-ready
    ready = session.query(InterventionRecord.id).filter(
        InterventionRecord.organization_name.isnot(None),
        InterventionRecord.intervention_title != "",
        InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())
    ).count()

    # Quarantined / rejected
    rejected = session.query(InterventionRecord).filter(InterventionRecord.result_status == "rejected").count()

    # Tiers
    tiers = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())

    pending = sum(c for t, c in tiers.items() if t in ("pending", "tier2", "tier3"))
    gold = tiers.get("gold", 0)
    silver = tiers.get("silver", 0)
    bronze = tiers.get("bronze", 0)

    # Sources by domain
    src_sql = session.query(Document.url).all()
    domains = {}
    for (url,) in src_sql:
        if url:
            try:
                from urllib.parse import urlparse
                d = urlparse(url).netloc
                domains[d] = domains.get(d, 0) + 1
            except: pass

    # Missing fields
    missing_org = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.organization_name.isnot(None)).count()
    missing_interv = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.intervention_title != "").count()
    missing_outcome = total_recs - with_metrics
    missing_timeline = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.intervention_implementation_time_value.isnot(None)).count()
    missing_orgsize = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.organization_employee_count.isnot(None)).count()
    missing_baseline = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.has_baseline == True).count()
    missing_industry = total_recs - session.query(InterventionRecord.id).filter(InterventionRecord.organization_industry != "[]", InterventionRecord.organization_industry.isnot(None)).count()

    # Industry coverage
    ind_sql = session.query(InterventionRecord.organization_industry).all()
    industries = {}
    for row in ind_sql:
        vals = row[0] if row[0] else []
        if isinstance(vals, str):
            try: vals = json.loads(vals)
            except: vals = [vals]
        for v in vals:
            v = v.strip().lower() if isinstance(v, str) else str(v).lower()
            if v and v != "unknown":
                industries[v] = industries.get(v, 0) + 1

    # Business function coverage
    bf_sql = session.query(InterventionRecord.problem_business_function).all()
    bfuncs = {}
    for row in bf_sql:
        vals = row[0] if row[0] else []
        if isinstance(vals, str):
            try: vals = json.loads(vals)
            except: vals = [vals]
        for v in vals:
            v = v.strip().lower() if isinstance(v, str) else str(v).lower()
            if v and v != "unknown":
                bfuncs[v] = bfuncs.get(v, 0) + 1

    # Intervention family coverage
    fam_sql = session.query(InterventionRecord.intervention_families).all()
    fams = {}
    for row in fam_sql:
        vals = row[0] if row[0] else []
        if isinstance(vals, str):
            try: vals = json.loads(vals)
            except: vals = [vals]
        for v in vals:
            v = v.strip().lower() if isinstance(v, str) else str(v).lower()
            if v:
                fams[v] = fams.get(v, 0) + 1

    # Metric categories
    metric_cats = dict(session.query(MetricRecord.metric_category, func.count(MetricRecord.id)).group_by(MetricRecord.metric_category).all())

    # Success vs failure
    success = session.query(InterventionRecord).filter(InterventionRecord.result_status == "successful").count()
    failures = session.query(InterventionRecord).filter(InterventionRecord.result_status.in_(["failed", "abandoned"])).count()
    partial = session.query(InterventionRecord).filter(InterventionRecord.result_status == "partial").count()

    # Average completeness score
    completeness_scores = []
    for rec in session.query(InterventionRecord).all():
        score = 0
        if rec.organization_name: score += 10
        if rec.intervention_title: score += 10
        if rec.organization_industry and rec.organization_industry not in ("[]", [""]): score += 10
        mc = session.query(MetricRecord).filter_by(intervention_id=rec.id).count()
        if mc > 0: score += 15
        if session.query(MetricRecord).filter_by(intervention_id=rec.id).filter(MetricRecord.percentage_change.isnot(None) | MetricRecord.absolute_change.isnot(None)).count() > 0: score += 15
        if rec.has_baseline: score += 10
        if rec.intervention_implementation_time_value: score += 10
        if rec.organization_employee_count: score += 10
        if rec.independently_verified: score += 10
        completeness_scores.append(score)
    avg_completeness = round(sum(completeness_scores) / max(len(completeness_scores), 1), 1)

    return {
        "documents": {"total": total_docs, "fetched": fetched, "parsed": parsed, "failed": failed},
        "implementations": {"total": total_recs, "recommendation_ready": ready, "rejected": rejected, "unique_orgs": session.query(InterventionRecord.organization_name).distinct().count(), "with_metrics": with_metrics, "quantified": quantified},
        "tiers": {"gold": gold, "silver": silver, "bronze": bronze, "pending": pending, "tier2": tiers.get("tier2", 0), "tier3": tiers.get("tier3", 0)},
        "targets": {"gold_target": 300, "silver_target": 300, "bronze_target": 300, "gold_gap": max(0, 300 - gold), "silver_gap": max(0, 300 - silver), "bronze_gap": max(0, 300 - bronze)},
        "outcomes": {"success": success, "partial": partial, "failed": failures},
        "quality": {"avg_completeness": avg_completeness, "missing_org": missing_org, "missing_intervention": missing_interv, "missing_outcome": missing_outcome, "missing_timeline": missing_timeline, "missing_org_size": missing_orgsize, "missing_baseline": missing_baseline, "missing_industry": missing_industry},
        "coverage": {"industries": dict(sorted(industries.items(), key=lambda x: -x[1])[:30]), "business_functions": dict(sorted(bfuncs.items(), key=lambda x: -x[1])[:15]), "intervention_families": dict(sorted(fams.items(), key=lambda x: -x[1])[:20]), "metric_categories": dict(sorted(metric_cats.items(), key=lambda x: -x[1])), "source_domains": dict(sorted(domains.items(), key=lambda x: -x[1])[:20])},
    }


def print_report(s):
    print("\n" + "=" * 72)
    print("  COMPASS EVIDENCE GRAPH ANALYTICS")
    print("=" * 72)
    print(f"\n  DOCUMENTS")
    print(f"    Total:           {s['documents']['total']}")
    print(f"    Fetched:         {s['documents']['fetched']}")
    print(f"    Parsed:          {s['documents']['parsed']}")
    print(f"    Failed:          {s['documents']['failed']}")

    print(f"\n  IMPLEMENTATIONS")
    print(f"    Total:           {s['implementations']['total']}")
    print(f"    Recommendation-ready: {s['implementations']['recommendation_ready']}")
    print(f"    Unique orgs:     {s['implementations']['unique_orgs']}")
    print(f"    With metrics:    {s['implementations']['with_metrics']}")
    print(f"    Quantified:      {s['implementations']['quantified']}")
    print(f"    Rejected:        {s['implementations']['rejected']}")

    print(f"\n  TIERS")
    for t in ['gold', 'silver', 'bronze']:
        pct = round(s['tiers'][t] / 300 * 100, 1) if s['tiers'][t] > 0 else 0
        print(f"    {t.title():8s}: {s['tiers'][t]:>3d} / 300 ({pct}%)  gap={s['targets'][t + '_gap']}")
    print(f"    Pending:         {s['tiers']['pending']}")

    print(f"\n  QUALITY")
    print(f"    Avg completeness: {s['quality']['avg_completeness']}/100")
    print(f"    Missing org:      {s['quality']['missing_org']}")
    print(f"    Missing industry: {s['quality']['missing_industry']}")
    print(f"    Missing timeline: {s['quality']['missing_timeline']}")
    print(f"    Missing baseline: {s['quality']['missing_baseline']}")
    print(f"    Missing org size: {s['quality']['missing_org_size']}")

    print(f"\n  OUTCOMES")
    print(f"    Successful:      {s['outcomes']['success']}")
    print(f"    Partial:         {s['outcomes']['partial']}")
    print(f"    Failed/abandoned: {s['outcomes']['failed']}")

    print(f"\n  TOP INDUSTRIES")
    for ind, c in list(s['coverage']['industries'].items())[:10]:
        print(f"    {ind}: {c}")

    print(f"\n  TOP BUSINESS FUNCTIONS")
    for bf, c in list(s['coverage']['business_functions'].items())[:10]:
        print(f"    {bf}: {c}")

    print(f"\n  TOP INTERVENTION FAMILIES")
    for f, c in list(s['coverage']['intervention_families'].items())[:10]:
        print(f"    {f}: {c}")

    print(f"\n  TOP SOURCE DOMAINS")
    for d, c in list(s['coverage']['source_domains'].items())[:10]:
        print(f"    {d}: {c}")

    print(f"\n  METRIC CATEGORIES")
    for mc, c in list(s['coverage']['metric_categories'].items())[:10]:
        print(f"    {mc}: {c}")
    print("=" * 72)


if __name__ == "__main__":
    session = get_session()
    stats = collect_stats(session)
    session.close()
    if "--json" in sys.argv:
        print(json.dumps(stats, indent=2))
    else:
        print_report(stats)
