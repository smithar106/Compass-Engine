#!/usr/bin/env python3
"""Audit a random sample of interventions for extraction quality."""

import sys, os, json, random, csv
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.config.settings import DATA_DIR

init_db()
session = get_session()

SAMPLE_SIZE = 50
random.seed(42)

interventions = session.query(InterventionRecord).all()
random_sample = random.sample(interventions, min(SAMPLE_SIZE, len(interventions)))

print(f"Auditing {len(random_sample)} randomly sampled interventions\n")

doc_cache = {}
rows = []
for i, inv in enumerate(random_sample):
    if inv.document_id not in doc_cache:
        doc_cache[inv.document_id] = session.query(Document).filter_by(id=inv.document_id).first()
    doc = doc_cache[inv.document_id]

    text_preview = ""
    if doc:
        text = doc.cleaned_text or ""
        text_preview = text[:500] if len(text) > 500 else text

    metrics = session.query(MetricRecord).filter_by(intervention_id=inv.id).all()
    metric_summary = "; ".join([
        f"{m.metric_name}: baseline={m.baseline_value}, post={m.post_value}, change={m.percentage_change or m.absolute_change}{'%' if m.percentage_change else ''}"
        for m in metrics[:5]
    ])

    row = {
        "id": i + 1,
        "intervention_id": inv.id,
        "document_title": doc.title if doc else "",
        "org_name": inv.organization_name or "—",
        "org_type": inv.organization_type or "—",
        "org_industry": ", ".join(inv.organization_industry or []),
        "problem_statement": (inv.problem_statement or "")[:150],
        "intervention_title": inv.intervention_title or "",
        "intervention_families": ", ".join(inv.intervention_families or []),
        "intervention_description": (inv.intervention_description or "")[:200],
        "result_status": inv.result_status or "unknown",
        "vendor_reported": inv.vendor_reported,
        "independently_verified": inv.independently_verified,
        "sample_size": inv.sample_size or "—",
        "has_control_group": inv.has_control_group,
        "implementation_cost": inv.intervention_implementation_cost,
        "implementation_time": f"{inv.intervention_implementation_time_value} {inv.intervention_implementation_time_unit or ''}" if inv.intervention_implementation_time_value else "—",
        "intervention_software": ", ".join(inv.intervention_software or []),
        "intervention_vendors": ", ".join(inv.intervention_vendors or []),
        "metrics": metric_summary or "—",
        "text_preview": text_preview,
    }
    rows.append(row)

    print(f"=== #{i+1} ===")
    print(f"  Title: {row['document_title'][:80]}")
    print(f"  Org: {row['org_name']}")
    print(f"  Problem: {row['problem_statement'][:120]}")
    print(f"  Intervention: {row['intervention_title'][:80]}")
    print(f"  Families: {row['intervention_families']}")
    print(f"  Status: {row['result_status']}")
    print(f"  Metrics: {row['metrics'][:120]}")
    print(f"  Cost: {row['implementation_cost']}")
    print(f"  Time: {row['implementation_time']}")
    print(f"  Verified: {row['independently_verified']}, Vendor: {row['vendor_reported']}")
    print()

# Save to CSV for review
ts = datetime.now().isoformat()[:19].replace(":", "-")
out_path = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / "data" / "extraction" / f"audit_sample_{ts}.csv"
out_path = out_path.resolve()
with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"Audit CSV: {out_path}")
session.close()
