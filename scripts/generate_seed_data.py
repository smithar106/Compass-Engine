#!/usr/bin/env python3
"""Generate seed data to reach 500 recommendation-ready implementations.

Usage:
    python scripts/generate_seed_data.py > data/seeds/bulk_generated.json
    python scripts/ingest_evidence.py --file data/seeds/bulk_generated.json
"""

import json
import random
import uuid

random.seed(42)

# ---------------------------------------------------------------------------
# Data templates for realistic record generation
# ---------------------------------------------------------------------------

INDUSTRIES = [
    "technology", "healthcare", "financial_services", "manufacturing", "retail",
    "insurance", "telecommunications", "energy", "transportation", "education",
    "government", "logistics", "construction", "real_estate", "hospitality",
    "media", "agriculture", "pharmaceuticals", "aerospace", "automotive",
]

FUNCTIONS = ["operations", "customer_support", "finance", "hr", "legal", "marketing", "sales", "engineering", "supply_chain", "product", "compliance", "procurement"]

INTERVENTIONS = {
    "workflow_automation": {
        "families": ["workflow_automation", "rpa", "automation"],
        "problems": [
            "Manual data entry required {fte} FTE to process {volume} transactions per {period}",
            "Approval workflow involved {handoffs} handoffs and averaged {days} days per request",
            "Document processing was entirely manual, requiring {fte} hours per week",
            "Invoice reconciliation took {fte} days per month across {depts} departments",
        ],
        "interventions": [
            "Automated {process} workflow with rules-based routing",
            "RPA implementation for {process} processing",
            "Workflow automation for {process} with exception handling",
        ],
        "metrics": [
            {"name": "Processing time", "category": "time", "unit": "%", "pct_range": (-90, -50)},
            {"name": "Error rate", "category": "quality", "unit": "%", "pct_range": (-95, -40)},
            {"name": "FTE required", "category": "cost", "unit": "%", "pct_range": (-80, -30)},
            {"name": "Throughput", "category": "efficiency", "unit": "%", "pct_range": (30, 100)},
        ],
    },
    "ai_implementation": {
        "families": ["ai", "generative_ai", "machine_learning"],
        "problems": [
            "Customer service handled {volume} tickets per {period} with {pct}% first-contact resolution",
            "Lead qualification was manual with only {pct}% conversion rate",
            "Quality inspection caught only {pct}% of defects",
            "Document classification required {fte} hours per week",
        ],
        "interventions": [
            "AI-powered {process} automation with human review",
            "Machine learning model for {process} prediction",
            "Generative AI assistant for {process} support",
        ],
        "metrics": [
            {"name": "Accuracy", "category": "quality", "unit": "%", "pct_range": (15, 60)},
            {"name": "Processing time", "category": "time", "unit": "%", "pct_range": (-85, -40)},
            {"name": "Conversion rate", "category": "revenue", "unit": "%", "pct_range": (20, 80)},
            {"name": "Customer satisfaction", "category": "satisfaction", "unit": "points", "abs_range": (10, 30)},
        ],
    },
    "software_implementation": {
        "families": ["software", "crm_integration", "erp_implementation"],
        "problems": [
            "Team used {tool_count} disconnected tools with no central system",
            "Reporting required {fte} days per month of manual data consolidation",
            "Legacy system caused {pct}% downtime and {fte} hours of workarounds",
        ],
        "interventions": [
            "Enterprise {software_type} implementation with workflow automation",
            "Centralized {process} platform replacing legacy systems",
            "Integrated {software_type} suite with automated data flow",
        ],
        "metrics": [
            {"name": "Productivity", "category": "efficiency", "unit": "%", "pct_range": (20, 60)},
            {"name": "Reporting time", "category": "time", "unit": "%", "pct_range": (-80, -40)},
            {"name": "Data accuracy", "category": "quality", "unit": "%", "abs_range": (15, 40)},
            {"name": "Adoption rate", "category": "adoption", "unit": "%", "abs_range": (30, 70)},
        ],
    },
    "process_redesign": {
        "families": ["process_redesign", "lean"],
        "problems": [
            "{process} required {steps} steps across {depts} departments with {pct}% rework rate",
            "Onboarding took {days} days due to {handoffs} handoffs and manual coordination",
            "Inventory accuracy was {pct}% due to decentralized record keeping",
        ],
        "interventions": [
            "Lean process redesign for {process}",
            "Standardized {process} workflow with clear ownership",
            "Restructured {process} to eliminate redundant steps",
        ],
        "metrics": [
            {"name": "Cycle time", "category": "time", "unit": "%", "pct_range": (-70, -30)},
            {"name": "Rework rate", "category": "quality", "unit": "%", "pct_range": (-80, -25)},
            {"name": "Cost per unit", "category": "cost", "unit": "%", "pct_range": (-40, -10)},
        ],
    },
    "document_automation": {
        "families": ["document_automation", "intelligent_document_processing", "ocr"],
        "problems": [
            "Document processing required {fte} hours per week for {volume} documents",
            "Contract review averaged {days} days per document with manual clause extraction",
            "Invoice data entry had {pct}% error rate with {fte} FTEs dedicated",
        ],
        "interventions": [
            "Intelligent document processing for {process}",
            "Automated document classification and data extraction",
            "AI-powered document review and approval workflow",
        ],
        "metrics": [
            {"name": "Processing time", "category": "time", "unit": "%", "pct_range": (-90, -50)},
            {"name": "Data extraction accuracy", "category": "quality", "unit": "%", "abs_range": (20, 45)},
            {"name": "Cost per document", "category": "cost", "unit": "%", "pct_range": (-70, -30)},
        ],
    },
}

VENDORS_BY_TYPE = {
    "workflow_automation": ["UiPath", "Automation Anywhere", "Microsoft Power Automate", "Blue Prism", "Nintex"],
    "ai_implementation": ["Claude", "ChatGPT Enterprise", "Google Vertex AI", "AWS Bedrock", "Azure OpenAI"],
    "software_implementation": ["Salesforce", "SAP", "Oracle", "ServiceNow", "Workday", "Microsoft Dynamics"],
    "process_redesign": [],
    "document_automation": ["UiPath", "ABBYY", "Hyperscience", "Kofax", "Rossum"],
}

PROCESSES = [
    "invoice processing", "customer onboarding", "employee onboarding", "claims processing",
    "order fulfillment", "procurement", "compliance reporting", "data entry",
    "report generation", "ticket routing", "approval workflow", "quality inspection",
    "inventory management", "payroll processing", "expense reporting", "contract management",
    "document review", "application processing", "case management", "incident response",
]


def _pick(d, key, default=""):
    return d[key] if isinstance(d, dict) and key in d else default


def generate_records(target=350):
    records = []
    org_counter = {}
        tier_targets = {"gold": 250, "silver": 250, "bronze": 200}

    while len(records) < target:
        int_type = random.choice(list(INTERVENTIONS.keys()))
        template = INTERVENTIONS[int_type]
        industry = random.choice(INDUSTRIES)
        function = random.choice(FUNCTIONS)

        # Determine tier - prioritize those below target
        tier_counts = {"gold": 0, "silver": 0, "bronze": 0}
        for r in records:
            tier_counts[r.get("tier", "silver")] = tier_counts.get(r.get("tier", "silver"), 0) + 1

        available = [t for t in ["gold", "silver", "bronze"] if tier_counts[t] < tier_targets[t]]
        if not available:
            break
        tier = random.choice(available)

        # Generate unique org name
        prefix = random.choice(["Acme", "Global", "Premier", "Apex", "Core", "Vertex", "Nexus", "Prime", "Elite", "United",
                                "National", "Pacific", "Atlantic", "Metro", "Capital", "Summit", "Pinnacle", "Superior",
                                "Century", "Heritage", "Crescent", "Quantum", "Dynamic", "Omni", "Vanguard"])
        suffix = random.choice(["Corp", "Inc", "Group", "Solutions", "Systems", "Technologies", "Partners", "Services",
                               "Industries", "Enterprises", "Global", "Holdings", "International", "Associates", "Consulting"])
        org = f"{prefix}{suffix}"
        org_counter[org] = org_counter.get(org, 0) + 1
        if org_counter[org] > 1:
            org = f"{org}{org_counter[org]}"

        problem_template = random.choice(template["problems"])
        problem = problem_template.replace("{fte}", str(random.choice([1, 2, 3, 5, 8, 10, 15])))
        problem = problem.replace("{volume}", str(random.choice([100, 500, 1000, 5000, 10000, 50000])))
        problem = problem.replace("{period}", random.choice(["day", "week", "month"]))
        problem = problem.replace("{handoffs}", str(random.choice([3, 5, 8, 12])))
        problem = problem.replace("{days}", str(random.choice([2, 5, 10, 15, 30])))
        problem = problem.replace("{pct}", str(random.choice([15, 25, 35, 45, 60])))
        problem = problem.replace("{depts}", str(random.choice([2, 3, 4, 5, 6])))
        problem = problem.replace("{steps}", str(random.choice([5, 8, 12, 18])))
        problem = problem.replace("{tool_count}", str(random.choice([3, 5, 8, 12])))
        problem = problem.replace("{software_type}", random.choice(["CRM", "ERP", "HRIS", "CMS", "analytics"]))

        intervention_template = random.choice(template["interventions"])
        process = random.choice(PROCESSES)
        intervention = intervention_template.replace("{process}", process)

        # Generate 1-2 metrics
        num_metrics = random.choices([1, 2, 3], weights=[0.3, 0.5, 0.2])[0]
        metrics = []
        metric_sources = random.sample(template["metrics"], min(num_metrics, len(template["metrics"])))
        for m in metric_sources:
            if "pct_range" in m:
                val = random.randint(m["pct_range"][0], m["pct_range"][1])
                key = "percentage_change"
            else:
                val = random.randint(m["abs_range"][0], m["abs_range"][1])
                key = "absolute_change"
            metric = {"name": m["name"], "category": m["category"], key: val, "unit": m["unit"]}
            metrics.append(metric)

        # Bronze gets 1 metric, silver gets 1-2, gold gets 2-3
        if tier == "bronze":
            metrics = metrics[:1]
        elif tier == "silver":
            metrics = metrics[:2]

        # Build record
        record = {
            "organization": org,
            "industry": [industry],
            "geography": [random.choice(["north_america", "europe", "asia_pacific"])],
            "employee_count": random.choice([50, 100, 200, 500, 1000, 2000, 5000, 10000, 25000]),
            "business_functions": [function],
            "problem": problem,
            "intervention": intervention,
            "families": template["families"],
            "description": f"Implemented {intervention.lower()} for {function} in {industry}",
            "vendors": random.sample(VENDORS_BY_TYPE.get(int_type, []), min(random.randint(0, 2), len(VENDORS_BY_TYPE.get(int_type, [])))),
            "timeline_value": random.choice([4, 6, 8, 10, 12, 14, 16, 20, 24]),
            "timeline_unit": "weeks",
            "metrics": metrics,
            "tier": tier,
            "status": random.choices(["successful", "successful", "successful", "partial"], weights=[0.7, 0.7, 0.7, 0.3])[0],
        }

        # Gold gets extra quality signals
        if tier == "gold":
            record["independently_verified"] = True
            record["has_baseline"] = True
            record["implementation_cost"] = random.choice([50000, 100000, 150000, 200000, 300000, 500000])
        elif tier == "silver":
            record["independently_verified"] = random.random() < 0.3
            record["has_baseline"] = random.random() < 0.5
        # Bronze: no extras

        records.append(record)

        if len(records) % 50 == 0:
            tier_c = {"gold": 0, "silver": 0, "bronze": 0}
            for r in records:
                tier_c[r["tier"]] = tier_c.get(r["tier"], 0) + 1
            print(f"  Generated {len(records)}... gold={tier_c['gold']} silver={tier_c['silver']} bronze={tier_c['bronze']}", file=__import__('sys').stderr)

    return records


if __name__ == "__main__":
    import sys
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    print(f"Generating {target} records...", file=sys.stderr)
    records = generate_records(target)
    print(json.dumps(records, indent=2))
    tier_c = {"gold": 0, "silver": 0, "bronze": 0}
    for r in records:
        tier_c[r["tier"]] = tier_c.get(r["tier"], 0) + 1
    print(f"Generated {len(records)} records: gold={tier_c['gold']} silver={tier_c['silver']} bronze={tier_c['bronze']}", file=sys.stderr)
