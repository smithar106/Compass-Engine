#!/usr/bin/env python3
"""Demo the Compass recommendation engine — shows the full 'Why?' panel experience."""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.analysis.recommendation import recommend


DEMO_SCENARIOS = [
    {
        "name": "Cloud Infrastructure Cost Reduction",
        "workflow": "cloud_infrastructure_management",
        "business_function": "operations",
        "industry": "technology",
        "employee_count": 500,
        "desired_outcome": "cost",
    },
    {
        "name": "Customer Support Automation",
        "workflow": "ticketing",
        "business_function": "customer_support",
        "industry": "saas",
        "employee_count": 200,
        "desired_outcome": "response_time",
    },
    {
        "name": "Invoice Processing Automation",
        "workflow": "invoice_processing",
        "business_function": "finance",
        "industry": "financial_services",
        "employee_count": 1000,
        "desired_outcome": "cost",
    },
    {
        "name": "Lead Qualification AI",
        "workflow": "lead_qualification",
        "business_function": "sales",
        "industry": "technology",
        "employee_count": 300,
        "desired_outcome": "conversion_rate",
    },
    {
        "name": "HR Onboarding Automation",
        "workflow": "onboarding",
        "business_function": "human_resources",
        "industry": "healthcare",
        "employee_count": 2000,
        "desired_outcome": "time",
    },
]


def display_recommendation(scenario_name: str, result: dict):
    """Pretty-print a recommendation with the full Why panel."""
    width = 72
    print("=" * width)
    print(f"  COMPASS RECOMMENDATION")
    print(f"  {scenario_name}")
    print("=" * width)
    print()

    # Context
    ctx = result["recommendation_context"]
    print(f"  Context: {ctx['workflow'].replace('_',' ').title()} | {ctx['department'].replace('_',' ').title()} | {ctx['industry'].title()}")
    print()

    # Recommended interventions
    print("  Recommended Interventions:")
    print(f"  {'─' * (width-2)}")
    for i, r in enumerate(result["recommended_interventions"][:3]):
        print(f"  {i+1}. {r['family_name']}  —  Confidence: {r['confidence']}%")
        print(f"     {r['description'][:80]}")
        print(f"     Based on {r['comparable_count']} comparable implementations")
        if r["top_examples"]:
            for ex in r["top_examples"][:2]:
                print(f"     ├ {ex['summary'][:80]}")
                if ex["outcomes"]:
                    for o in ex["outcomes"][:2]:
                        print(f"     │  → {o}")
        print()

    # Confidence
    conf = result["overall_confidence"]
    print(f"  Overall Confidence: {conf['score']}%")
    print(f"  {conf['summary']}")
    print(f"  Factors: {json.dumps(conf['breakdown'])}")
    print()

    # Why panel
    why = result["why"]
    print("  ┌─ Why This Recommendation ─" + "─" * 40)
    print(f"  │ {why['why_this_recommendation'][:300]}")
    print(f"  │")
    print(f"  │ Comparable implementations: {why['comparable_implementations']['total']}")
    print(f"  │ Unique organizations: {why['comparable_implementations']['unique_organizations']}")
    print(f"  │ Status: {json.dumps(why['comparable_implementations']['status_breakdown'])}")
    print(f"  │")
    if why["negative_evidence"]:
        print(f"  │ ⚠ Failures to learn from:")
        for n in why["negative_evidence"][:2]:
            print(f"  │   • {n['organization']}: {'; '.join(n['failure_reasons'][:2])}")
    print(f"  │")
    print(f"  │ Alternatives considered:")
    for alt in why["alternative_interventions_considered"][:3]:
        print(f"  │   • {alt['family']}: {alt['reason']}")
    print(f"  └" + "─" * 50)
    print()


if __name__ == "__main__":
    scenario_idx = 0
    if len(sys.argv) > 1:
        try:
            scenario_idx = int(sys.argv[1]) - 1
        except ValueError:
            pass

    if scenario_idx >= len(DEMO_SCENARIOS):
        scenario_idx = 0

    scenario = DEMO_SCENARIOS[scenario_idx]
    print(f"\n  Running scenario: {scenario['name']}\n")
    print(f"  Workflow: {scenario['workflow'].replace('_', ' ').title()}")
    print(f"  Department: {scenario['business_function'].replace('_', ' ').title()}")
    print(f"  Industry: {scenario['industry'].title()}")
    print(f"  Company size: ~{scenario['employee_count']} employees")
    print(f"  Desired outcome: {scenario['desired_outcome'].replace('_', ' ').title()}")
    print()

    result = recommend(**{k: v for k, v in scenario.items() if k != "name"})
    display_recommendation(scenario["name"], result)
