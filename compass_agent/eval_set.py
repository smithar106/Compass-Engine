"""Retrieval evaluation set.

A fixed set of representative Compass requests, each with a profile and
relevance labels defined as deterministic predicates over canonical record
attributes (workflow, canonical industry, evidence tier, result status).

Labels are seed/provisional — the harness + metrics are the deliverable, and
labels should be refined by a human reviewer. The predicates make the eval
runnable today against any record pool and reproducible.

For each request:
  profile:  the query fields (workflow, business_function, industry, size,
            geography, problem_statement, desired_outcome)
  relevant: records that should rank top (workflow AND industry match)
  somewhat: workflow OR industry match
  irrelevant: neither — must NOT influence the recommendation
  expected_families: intervention families that should rank first
  excluded_tier: evidence tier that should not influence (e.g. rejected)
"""

EVAL_REQUESTS: list[dict] = [
    {
        "id": "invoice_processing_bank",
        "profile": {
            "workflow": "invoice_processing",
            "business_function": "finance",
            "industry": "banking",
            "company_size": "5000",
            "desired_outcome": "time",
            "problem_statement": "Manual invoice processing is slow and error-prone; matching errors cause rework.",
        },
        "workflow": "invoice_processing",
        "industry": "financial_services",
        "expected_families": ["workflow_automation", "ai", "rpa"],
    },
    {
        "id": "onboarding_customer_success",
        "profile": {
            "workflow": "onboarding",
            "business_function": "customer_success",
            "industry": "technology",
            "company_size": "1000",
            "desired_outcome": "time",
            "problem_statement": "Customer onboarding takes 45 days because approvals and setup are manual.",
        },
        "workflow": "onboarding",
        "industry": "technology",
        "expected_families": ["workflow_automation", "software", "process_redesign"],
    },
    {
        "id": "support_ticketing_healthcare",
        "profile": {
            "workflow": "ticketing",
            "business_function": "customer_support",
            "industry": "healthcare",
            "company_size": "2000",
            "desired_outcome": "time",
            "problem_statement": "Support tickets pile up and resolution time is high.",
        },
        "workflow": "ticketing",
        "industry": "healthcare",
        "expected_families": ["workflow_automation", "ai"],
    },
    {
        "id": "lead_qualification_sales",
        "profile": {
            "workflow": "lead_qualification",
            "business_function": "sales",
            "industry": "technology",
            "company_size": "1000",
            "desired_outcome": "revenue",
            "problem_statement": "Sales team manually qualifies leads across channels with no scoring.",
        },
        "workflow": "lead_qualification",
        "industry": "technology",
        "expected_families": ["ai", "workflow_automation", "software"],
    },
    {
        "id": "marketing_automation",
        "profile": {
            "workflow": "marketing_automation",
            "business_function": "marketing",
            "industry": "retail_consumer",
            "company_size": "500",
            "desired_outcome": "revenue",
            "problem_statement": "Email campaigns are manual broadcasts with no segmentation.",
        },
        "workflow": "marketing_automation",
        "industry": "retail_consumer",
        "expected_families": ["process_redesign", "software"],
    },
    {
        "id": "ci_cd_engineering",
        "profile": {
            "workflow": "ci_cd",
            "business_function": "engineering",
            "industry": "technology",
            "company_size": "1000",
            "desired_outcome": "efficiency",
            "problem_statement": "No CI/CD pipeline; deployments are manual and slow.",
        },
        "workflow": "ci_cd",
        "industry": "technology",
        "expected_families": ["software", "process_redesign"],
    },
    {
        "id": "contract_review_legal",
        "profile": {
            "workflow": "contract_review",
            "business_function": "legal",
            "industry": "financial_services",
            "company_size": "5000",
            "desired_outcome": "time",
            "problem_statement": "Contract review is serial and human-only; backlog compounds.",
        },
        "workflow": "contract_review",
        "industry": "financial_services",
        "expected_families": ["ai", "software", "process_redesign"],
    },
    {
        "id": "supply_chain_inventory",
        "profile": {
            "workflow": "supply_chain",
            "business_function": "operations",
            "industry": "retail_consumer",
            "company_size": "5000",
            "desired_outcome": "efficiency",
            "problem_statement": "Inventory and logistics coordination is manual across systems.",
        },
        "workflow": "supply_chain",
        "industry": "retail_consumer",
        "expected_families": ["software", "workflow_automation"],
    },
    {
        "id": "manufacturing_quality",
        "profile": {
            "workflow": "manufacturing",
            "business_function": "operations",
            "industry": "manufacturing",
            "company_size": "10000",
            "desired_outcome": "quality",
            "problem_statement": "Quality control has manual checkpoints; defects surface late.",
        },
        "workflow": "manufacturing",
        "industry": "manufacturing",
        "expected_families": ["process_redesign", "software"],
    },
    {
        "id": "customer_health_scoring",
        "profile": {
            "workflow": "customer_health",
            "business_function": "customer_success",
            "industry": "technology",
            "company_size": "1000",
            "desired_outcome": "revenue",
            "problem_statement": "CS team cannot identify at-risk accounts before they churn.",
        },
        "workflow": "customer_health",
        "industry": "technology",
        "expected_families": ["software", "ai"],
    },
    {
        "id": "financial_close",
        "profile": {
            "workflow": "financial_close",
            "business_function": "finance",
            "industry": "financial_services",
            "company_size": "5000",
            "desired_outcome": "time",
            "problem_statement": "Month-end close takes 12 days with manual reconciliation.",
        },
        "workflow": "financial_close",
        "industry": "financial_services",
        "expected_families": ["workflow_automation", "software"],
    },
    {
        "id": "claims_processing_insurance",
        "profile": {
            "workflow": "claims_processing",
            "business_function": "operations",
            "industry": "insurance",
            "company_size": "5000",
            "desired_outcome": "time",
            "problem_statement": "Claims processing is manual and slow; fraud checks add delay.",
        },
        "workflow": "claims_processing",
        "industry": "financial_services",
        "expected_families": ["workflow_automation", "ai"],
    },
    {
        "id": "payroll_hr",
        "profile": {
            "workflow": "payroll",
            "business_function": "human_resources",
            "industry": "professional_services",
            "company_size": "500",
            "desired_outcome": "quality",
            "problem_statement": "Payroll is manual across entities; errors cause disputes.",
        },
        "workflow": "payroll",
        "industry": "professional_services",
        "expected_families": ["software", "workflow_automation"],
    },
    {
        "id": "it_helpdesk",
        "profile": {
            "workflow": "helpdesk",
            "business_function": "it",
            "industry": "technology",
            "company_size": "1000",
            "desired_outcome": "time",
            "problem_statement": "IT help desk tickets are routed manually with no automation.",
        },
        "workflow": "helpdesk",
        "industry": "technology",
        "expected_families": ["workflow_automation", "ai", "software"],
    },
    {
        "id": "sales_forecasting",
        "profile": {
            "workflow": "sales_forecasting",
            "business_function": "sales",
            "industry": "retail_consumer",
            "company_size": "5000",
            "desired_outcome": "revenue",
            "problem_statement": "Sales forecasting is a manual spreadsheet exercise.",
        },
        "workflow": "sales_forecasting",
        "industry": "retail_consumer",
        "expected_families": ["ai", "software"],
    },
]
