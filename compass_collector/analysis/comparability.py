"""Comparability dimensions for matching comparable implementations."""

# ── Problem Dimensions ──
BUSINESS_FUNCTIONS = [
    "sales", "marketing", "customer_support", "finance", "accounting",
    "human_resources", "it", "engineering", "operations", "supply_chain",
    "legal", "compliance", "procurement", "product", "design", "research",
]

WORKFLOWS = {
    "sales": [
        "lead_qualification", "proposal_generation", "contract_management",
        "pipeline_management", "account_planning", "forecasting",
    ],
    "marketing": [
        "campaign_management", "content_generation", "seo_optimization",
        "social_media", "email_marketing", "analytics_reporting",
        "lead_scoring", "personalization",
    ],
    "customer_support": [
        "ticketing", "chat", "call_routing", "knowledge_base",
        "self_service", "sentiment_analysis", "quality_assurance",
    ],
    "finance": [
        "invoice_processing", "accounts_payable", "accounts_receivable",
        "financial_reporting", "budgeting", "forecasting",
        "audit", "expense_management", "revenue_recognition",
    ],
    "accounting": [
        "general_ledger", "reconciliation", "tax_preparation",
        "payroll", "fixed_assets", "intercompany_accounting",
    ],
    "human_resources": [
        "recruiting", "onboarding", "payroll", "benefits_administration",
        "performance_management", "learning_development",
        "employee_engagement", "compliance_training",
    ],
    "it": [
        "helpdesk", "identity_management", "access_management",
        "infrastructure_monitoring", "incident_response",
        "change_management", "asset_management", "backup_recovery",
        "cloud_migration", "network_management", "security_operations",
    ],
    "engineering": [
        "code_review", "ci_cd", "deployment", "testing",
        "incident_response", "capacity_planning", "performance_optimization",
        "api_management", "database_migration",
    ],
    "operations": [
        "order_processing", "inventory_management", "warehouse_management",
        "logistics", "scheduling", "quality_control",
        "facilities_management", "procurement",
    ],
    "supply_chain": [
        "demand_forecasting", "inventory_optimization", "supplier_management",
        "logistics_planning", "warehouse_automation", "order_fulfillment",
    ],
    "legal": [
        "contract_review", "discovery", "compliance_monitoring",
        "intellectual_property", "risk_assessment",
    ],
    "compliance": [
        "regulatory_reporting", "policy_management", "audit_trail",
        "access_governance", "data_privacy",
    ],
    "procurement": [
        "vendor_selection", "purchase_order", "contract_negotiation",
        "spend_analysis", "supplier_evaluation",
    ],
    "product": [
        "requirements_management", "roadmap_planning", "user_research",
        "a_b_testing", "feature_prioritization", "analytics",
    ],
    "design": [
        "design_systems", "prototyping", "user_testing",
        "accessibility", "design_handoff",
    ],
    "research": [
        "literature_review", "experiment_design", "data_collection",
        "statistical_analysis", "publication",
    ],
}

ALL_WORKFLOWS = sorted(set(w for func in WORKFLOWS.values() for w in func))

# ── Company Dimensions ──
INDUSTRIES = [
    "technology", "healthcare", "financial_services", "manufacturing",
    "retail", "energy", "education", "government", "telecommunications",
    "transportation", "real_estate", "media", "agriculture",
    "construction", "hospitality", "insurance", "pharmaceutical",
]

EMPLOYEE_BANDS = [
    "<10", "10-50", "50-200", "200-1000", "1000-10000", "10000+",
]

REVENUE_BANDS = [
    "<1M", "1M-10M", "10M-100M", "100M-1B", "1B-10B", "10B+",
]

# ── Intervention Dimensions ──
INTERVENTION_CATEGORIES = [
    "AI",
    "Software",
    "Workflow_Automation",
    "Process_Redesign",
    "Staffing",
    "Hybrid",
    "Other",
]

INTERVENTION_SUBCATEGORIES = {
    "AI": [
        "generative_ai", "predictive_ai", "computer_vision", "nlp",
        "recommendation_system", "anomaly_detection", "chatbot",
        "intelligent_automation", "ml_ops",
    ],
    "Software": [
        "crm_implementation", "erp_implementation", "cloud_migration",
        "saas_adoption", "platform_migration", "api_integration",
        "database_migration", "devops_tools",
    ],
    "Workflow_Automation": [
        "rpa", "workflow_automation", "business_process_automation",
        "document_automation", "approval_workflow",
    ],
    "Process_Redesign": [
        "lean", "six_sigma", "business_process_reengineering",
        "organizational_restructuring", "agile_transformation",
        "center_of_excellence", "shared_services",
    ],
    "Staffing": [
        "hiring", "training", "outsourcing", "offshoring",
        "reorganization", "role_consolidation",
    ],
    "Hybrid": [
        "ai_human_collaboration", "augmented_workflow",
        "assisted_decision_making", "human_in_the_loop",
    ],
}

ALL_SUBCATEGORIES = sorted(set(s for cat in INTERVENTION_SUBCATEGORIES.values() for s in cat))

# ── Outcome Dimensions ──
OUTCOME_CATEGORIES = [
    "time", "cost", "revenue", "quality", "satisfaction",
    "adoption", "risk", "productivity", "efficiency", "accuracy",
]

OUTCOME_METRICS_BY_CATEGORY = {
    "time": [
        "cycle_time", "response_time", "resolution_time",
        "processing_time", "lead_time", "time_to_market",
        "downtime", "uptime", "latency", "throughput",
    ],
    "cost": [
        "cost_savings", "cost_per_unit", "total_cost_of_ownership",
        "operating_expense", "labor_cost", "infrastructure_cost",
        "cost_per_transaction", "cost_per_lead",
    ],
    "revenue": [
        "revenue_increase", "revenue_per_customer",
        "average_order_value", "customer_lifetime_value",
        "conversion_rate", "win_rate", "upsell_rate",
    ],
    "quality": [
        "error_rate", "defect_rate", "accuracy", "precision",
        "recall", "f1_score", "compliance_rate", "first_pass_yield",
    ],
    "satisfaction": [
        "customer_satisfaction", "nps", "csat", "employee_satisfaction",
        "user_satisfaction", "ces",
    ],
    "adoption": [
        "user_adoption_rate", "feature_adoption", "active_users",
        "retention_rate", "churn_rate", "engagement_rate",
    ],
    "risk": [
        "incident_count", "security_incidents", "compliance_violations",
        "fraud_detection_rate", "false_positive_rate",
    ],
    "productivity": [
        "output_per_employee", "units_per_hour", "tickets_resolved",
        "lines_of_code", "stories_completed",
    ],
    "efficiency": [
        "automation_rate", "straight_through_processing",
        "touches_per_order", "handling_time",
    ],
    "accuracy": [
        "forecast_accuracy", "prediction_accuracy",
        "classification_accuracy", "extraction_accuracy",
    ],
}


def dimension_score(intervention_a: dict, intervention_b: dict) -> float:
    """Compute similarity score between two interventions across all dimensions.
    Returns 0.0 (completely different) to 1.0 (identical)."""
    score = 0.0
    weights = {
        "industry": 0.15,
        "business_function": 0.20,
        "workflow": 0.25,
        "intervention_category": 0.20,
        "organization_size": 0.10,
        "outcome_category": 0.10,
    }

    # Industry match
    ind_a = set(intervention_a.get("organization_industry", []))
    ind_b = set(intervention_b.get("organization_industry", []))
    if ind_a and ind_b:
        score += weights["industry"] * (len(ind_a & ind_b) / len(ind_a | ind_b))

    # Business function match
    bf_a = set(intervention_a.get("problem_business_function", []))
    bf_b = set(intervention_b.get("problem_business_function", []))
    if bf_a and bf_b:
        score += weights["business_function"] * (len(bf_a & bf_b) / len(bf_a | bf_b))

    # Workflow match
    wf_a = intervention_a.get("workflow", "")
    wf_b = intervention_b.get("workflow", "")
    if wf_a and wf_b:
        score += weights["workflow"] * (1.0 if wf_a == wf_b else 0.3 if wf_a[:10] == wf_b[:10] else 0.0)

    # Intervention category match
    cat_a = intervention_a.get("intervention_category", "")
    cat_b = intervention_b.get("intervention_category", "")
    if cat_a and cat_b:
        score += weights["intervention_category"] * (1.0 if cat_a == cat_b else 0.0)

    # Organization size proximity
    size_a = intervention_a.get("organization_employee_count")
    size_b = intervention_b.get("organization_employee_count")
    if size_a and size_b:
        ratio = min(size_a, size_b) / max(size_a, size_b)
        score += weights["organization_size"] * ratio

    return score


def find_comparable(
    target: dict,
    candidates: list[dict],
    min_score: float = 0.3,
    max_results: int = 10,
) -> list[dict]:
    """Find implementations comparable to the target."""
    scored = []
    for c in candidates:
        s = dimension_score(target, c)
        if s >= min_score:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [{"score": s, "intervention": c} for s, c in scored[:max_results]]
