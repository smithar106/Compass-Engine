"""Benchmark suite

A fixed set of 25 operational problems with expected evidence matches
spanning problem categories, industries, and evidence tiers. Each problem
defines:
  - query: what the user would type
  - expected_categories: what intervention families should appear
  - expected_evidence mix: balance of gold/silver/bronze
  - expected_diversity: min unique organizations
  - expected_negative: should include risk/negative evidence
"""

BENCHMARK_PROBLEMS = [
    # ── Finance / Accounting ──
    {
        "id": "invoice_processing",
        "query": "Manual invoice processing is slow, error-prone, and requires 3-5 days per invoice",
        "business_function": "finance",
        "categories": ["workflow_automation", "ai", "rpa"],
        "min_evidence": 5,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 3,
        "expect_negative": True,
        "description": "AP automation, invoice OCR, workflow digitization",
    },
    {
        "id": "quote_to_order",
        "query": "Quotes take 2 weeks to turn into orders with 4 handoffs between sales and operations",
        "business_function": "sales",
        "categories": ["workflow_automation", "process_redesign", "software"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "CPQ, order management, sales-operations alignment",
    },
    {
        "id": "financial_reporting",
        "query": "Month-end close takes 12 days with manual reconciliation across 6 systems",
        "business_function": "finance",
        "categories": ["workflow_automation", "ai", "software"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Financial close automation, reconciliation, reporting consolidation",
    },
    {
        "id": "contract_review",
        "query": "Legal team reviews 200+ contracts per month manually, turnaround is 14 days",
        "business_function": "legal",
        "categories": ["ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "Contract AI, NLP review, clause extraction, legal workflow",
    },

    # ── Customer Operations ──
    {
        "id": "customer_onboarding",
        "query": "Customer onboarding takes 4-6 weeks with 8 different teams involved",
        "business_function": "customer_support",
        "categories": ["workflow_automation", "process_redesign", "software"],
        "min_evidence": 5,
        "min_gold": 1,
        "min_silver": 2,
        "min_orgs": 3,
        "expect_negative": True,
        "description": "Customer onboarding, KYC, account setup automation",
    },
    {
        "id": "support_escalation",
        "query": "70% of support tickets escalate to L2 because agents can't find answers in the knowledge base",
        "business_function": "customer_support",
        "categories": ["ai", "software"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "AI-powered knowledge retrieval, chatbot, agent assist",
    },
    {
        "id": "call_center_efficiency",
        "query": "Call center handles 50K calls/month with 12-minute average handle time and no deflection",
        "business_function": "customer_support",
        "categories": ["ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Call center AI, IVR, chatbot deflection, agent augmentation",
    },

    # ── Supply Chain / Logistics ──
    {
        "id": "inventory_forecasting",
        "query": "Inventory forecasting accuracy is 60%, leading to 15% stockouts and 20% overstock",
        "business_function": "supply_chain",
        "categories": ["ai", "software"],
        "min_evidence": 5,
        "min_gold": 1,
        "min_silver": 2,
        "min_orgs": 3,
        "expect_negative": True,
        "description": "Demand forecasting, inventory optimization, AI supply chain",
    },
    {
        "id": "returns_processing",
        "query": "Returns processing takes 5 days with 40% manual inspection rate and 12% error rate",
        "business_function": "operations",
        "categories": ["workflow_automation", "ai", "process_redesign"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Returns automation, reverse logistics, quality inspection AI",
    },
    {
        "id": "warehouse_operations",
        "query": "Warehouse pick accuracy is 92% with 4 hours lost daily to manual inventory counts",
        "business_function": "supply_chain",
        "categories": ["ai", "workflow_automation", "software"],
        "min_evidence": 4,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Warehouse automation, pick-pack AI, inventory robotics",
    },

    # ── IT / Engineering ──
    {
        "id": "incident_management",
        "query": "IT incidents take 4 hours to triage with 30% misrouted to wrong teams",
        "business_function": "it",
        "categories": ["ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "AIOps, incident routing, automated triage, observability",
    },
    {
        "id": "code_review_backlog",
        "query": "Code review backlog is 200+ PRs averaging 3 days to first review",
        "business_function": "engineering",
        "categories": ["ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "AI code review, automated testing, CI/CD optimization",
    },
    {
        "id": "data_quality",
        "query": "Data quality issues cause 15% of analytics queries to return incorrect results",
        "business_function": "it",
        "categories": ["ai", "software", "process_redesign"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Data quality monitoring, AI data validation, MDM",
    },

    # ── HR / People ──
    {
        "id": "hr_onboarding",
        "query": "Employee onboarding involves 12 forms, 5 departments, and takes 3 weeks",
        "business_function": "hr",
        "categories": ["workflow_automation", "software", "process_redesign"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 2,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "HR onboarding automation, employee self-service, IAM provisioning",
    },
    {
        "id": "talent_screening",
        "query": "Recruiters spend 60% of time screening resumes manually for 500 open positions",
        "business_function": "hr",
        "categories": ["ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "AI resume screening, talent matching, recruitment automation",
    },

    # ── Knowledge / Information ──
    {
        "id": "knowledge_trapped",
        "query": "Critical operational knowledge lives in 15,000 scattered spreadsheets and email threads",
        "business_function": "operations",
        "categories": ["ai", "software", "process_redesign"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "Knowledge management, enterprise search, AI knowledge extraction",
    },
    {
        "id": "reporting_bottleneck",
        "query": "Quarterly business reviews require 3 analysts working 2 weeks to compile from 40 data sources",
        "business_function": "operations",
        "categories": ["ai", "workflow_automation", "software"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Automated reporting, BI, dashboarding, data pipeline automation",
    },

    # ── Compliance / Risk ──
    {
        "id": "compliance_audit",
        "query": "SOC 2 audit preparation takes 8 weeks with evidence gathering across 20 systems",
        "business_function": "compliance",
        "categories": ["workflow_automation", "software", "ai"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "Compliance automation, audit evidence collection, continuous monitoring",
    },
    {
        "id": "fraud_detection",
        "query": "Payment fraud detection catches 60% of fraudulent transactions with 25% false positive rate",
        "business_function": "finance",
        "categories": ["ai", "software"],
        "min_evidence": 4,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": True,
        "description": "Fraud AI, anomaly detection, risk scoring, transaction monitoring",
    },

    # ── Industry-specific ──
    {
        "id": "claims_processing",
        "query": "Insurance claims processing takes 21 days from FNOL to settlement with 4 manual reviews",
        "business_function": "operations",
        "categories": ["ai", "workflow_automation", "software"],
        "min_evidence": 5,
        "min_gold": 1,
        "min_silver": 2,
        "min_orgs": 3,
        "expect_negative": True,
        "description": "Claims automation, FNOL, adjudication AI, insurance workflow",
    },
    {
        "id": "patient_scheduling",
        "query": "Patient appointment scheduling has 30% no-show rate and 45-minute average wait time",
        "business_function": "operations",
        "categories": ["ai", "software", "process_redesign"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Healthcare scheduling, patient engagement, capacity optimization",
    },
    {
        "id": "approval_chains",
        "query": "Capital expenditure approvals go through 7 sign-offs taking 15 business days on average",
        "business_function": "finance",
        "categories": ["workflow_automation", "process_redesign", "software"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Approval workflow automation, delegation rules, spend management",
    },
    {
        "id": "product_catalog",
        "query": "Product catalog management across 50K SKUs leads to 8% listing errors in e-commerce channels",
        "business_function": "operations",
        "categories": ["ai", "software", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "PIM, catalog automation, AI content enrichment, MDM",
    },
    {
        "id": "vendor_management",
        "query": "Managing 500+ vendors with manual scorecards updated quarterly creates 6-week information lag",
        "business_function": "procurement",
        "categories": ["software", "ai", "workflow_automation"],
        "min_evidence": 3,
        "min_gold": 0,
        "min_silver": 1,
        "min_orgs": 1,
        "expect_negative": False,
        "description": "Vendor management, supplier scorecards, procurement analytics",
    },
    {
        "id": "pricing_optimization",
        "query": "Dynamic pricing rules are maintained in Excel, leading to 3% margin leakage on 10M monthly transactions",
        "business_function": "sales",
        "categories": ["ai", "software"],
        "min_evidence": 3,
        "min_gold": 1,
        "min_silver": 1,
        "min_orgs": 2,
        "expect_negative": False,
        "description": "Pricing AI, dynamic pricing, margin optimization, revenue management",
    },
]


def get_all_problems():
    """Return all benchmark problems."""
    return BENCHMARK_PROBLEMS


def get_problems_by_function():
    """Return problems grouped by business function."""
    groups = {}
    for p in BENCHMARK_PROBLEMS:
        groups.setdefault(p["business_function"], []).append(p)
    return groups


def get_problem_by_id(problem_id: str):
    """Return a single benchmark problem by ID."""
    for p in BENCHMARK_PROBLEMS:
        if p["id"] == problem_id:
            return p
    return None
