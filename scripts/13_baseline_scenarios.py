#!/usr/bin/env python3
"""Run all 5 demo scenarios, save full output as a baseline for comparison after v2 extraction."""

import sys, os, json, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.analysis.recommendation import recommend

SCENARIOS = [
    {"name": "Cloud Infrastructure Cost Reduction", "workflow": "cloud_infrastructure_management", "business_function": "operations", "industry": "technology", "employee_count": 500, "desired_outcome": "cost"},
    {"name": "Customer Support Automation", "workflow": "ticketing", "business_function": "customer_support", "industry": "saas", "employee_count": 200, "desired_outcome": "response_time"},
    {"name": "Invoice Processing Automation", "workflow": "invoice_processing", "business_function": "finance", "industry": "financial_services", "employee_count": 1000, "desired_outcome": "cost"},
    {"name": "Lead Qualification AI", "workflow": "lead_qualification", "business_function": "sales", "industry": "technology", "employee_count": 300, "desired_outcome": "conversion_rate"},
    {"name": "HR Onboarding Automation", "workflow": "onboarding", "business_function": "human_resources", "industry": "healthcare", "employee_count": 2000, "desired_outcome": "time"},
]

output_dir = Path(__file__).resolve().parent.parent / "data" / "analysis"
output_dir.mkdir(parents=True, exist_ok=True)

baseline = {
    "generated_at": datetime.utcnow().isoformat(),
    "extraction_version": "v1",
    "documents_in_db": 0,
    "scenarios": [],
}

# Get DB doc count
from compass_collector.database import init_db, get_session
from compass_collector.models.intervention import InterventionRecord
init_db()
session = get_session()
baseline["documents_in_db"] = session.query(InterventionRecord).count()
session.close()

for s in SCENARIOS:
    print(f"\n=== Scenario: {s['name']} ===")
    t0 = time.time()
    params = {k: v for k, v in s.items() if k != "name"}
    result = recommend(**params)
    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s")

    scenario_record = {
        "scenario_name": s["name"],
        "query_params": params,
        "elapsed_seconds": round(elapsed, 1),
        "recommended_interventions": result["recommended_interventions"],
        "overall_confidence": result["overall_confidence"],
        "evidence_summary": result["evidence_summary"],
        "why": {
            "summary": result["why"]["why_this_recommendation"],
            "comparable_total": result["why"]["comparable_implementations"]["total"],
            "unique_organizations": result["why"]["comparable_implementations"]["unique_organizations"],
            "status_breakdown": result["why"]["comparable_implementations"]["status_breakdown"],
            "top_comparables": [
                {"organization": r["organization"], "intervention": r["intervention"], "outcome": r["outcome"], "similarity": r["similarity"], "status": r["status"]}
                for r in result["why"]["comparable_implementations"]["top_results"]
            ],
            "expected_outcomes": result["why"]["expected_outcomes"],
            "alternative_interventions": result["why"]["alternative_interventions_considered"],
            "negative_evidence": result["why"]["negative_evidence"],
        },
    }
    baseline["scenarios"].append(scenario_record)

# Save as v1 baseline
baseline_path = output_dir / "baseline_v1.json"
with open(baseline_path, "w") as f:
    json.dump(baseline, f, indent=2, default=str)
print(f"\nSaved baseline to {baseline_path}")
print(f"Total scenarios: {len(baseline['scenarios'])}")
print(f"Documents in DB: {baseline['documents_in_db']}")
