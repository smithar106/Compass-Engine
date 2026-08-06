"""Canonical workflow taxonomy + free-text inference.

Phase 4 completion — the workflow dimension of the canonical knowledge layer.

The evidence graph stores workflows as verbose free text
("customer service call handling and employee absence reporting"), so exact
matching fails. This module:

  * defines canonical workflow slugs (reusing ``ALL_WORKFLOWS`` from
    ``comparability.py`` — one canonical set, no drift)
  * maps free-text phrases → canonical slugs via exact aliases + an ordered
    keyword table (longest keywords first, deterministic first-match)
  * infers a workflow from arbitrary text (title/problem statement) for
    records that never stored one
  * maps canonical slug → business function (the ``WORKFLOWS`` reverse map)

Mirrors taxonomy.py conventions: deterministic, raw preserved, provenance
attached, unmapped values kept at low confidence (never dropped).
"""

from __future__ import annotations

import re
from typing import Optional

from compass_collector.analysis.comparability import ALL_WORKFLOWS, WORKFLOWS
from compass_collector.organization.taxonomy import NormalizedValue

WORKFLOW_NORMALIZATION_VERSION = "workflow-v1"

# Reverse map: canonical slug → business function.
_FUNCTION_BY_WORKFLOW: dict[str, str] = {
    wf: fn for fn, wfs in WORKFLOWS.items() for wf in wfs
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PAREN_RE = re.compile(r"\([^)]*\)")


def _clean(raw: str) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().lower()
    text = _PAREN_RE.sub(" ", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text).strip()


def workflow_function(slug: Optional[str]) -> Optional[str]:
    """Business function for a canonical workflow slug."""
    return _FUNCTION_BY_WORKFLOW.get(slug or "")


def slugify(raw: str) -> str:
    return _SLUG_RE.sub("_", str(raw or "").strip().lower()).strip("_")


# Exact alias: normalized phrase → canonical slug.
WORKFLOW_ALIASES: dict[str, str] = {
    "invoice processing": "invoice_processing",
    "invoice automation": "invoice_processing",
    "accounts payable": "accounts_payable",
    "accounts receivable": "accounts_receivable",
    "financial close": "financial_reporting",
    "financial reporting": "financial_reporting",
    "expense management": "expense_management",
    "revenue recognition": "revenue_recognition",
    "contract review": "contract_review",
    "contract management": "contract_management",
    "lead qualification": "lead_qualification",
    "proposal generation": "proposal_generation",
    "customer onboarding": "onboarding",
    "employee onboarding": "onboarding",
    "ticketing": "ticketing",
    "helpdesk": "helpdesk",
    "help desk": "helpdesk",
    "call routing": "call_routing",
    "knowledge base": "knowledge_base",
    "self service": "self_service",
    "warehouse management": "warehouse_management",
    "inventory management": "inventory_management",
    "inventory optimization": "inventory_optimization",
    "demand forecasting": "demand_forecasting",
    "supply chain": "supplier_management",
    "supplier management": "supplier_management",
    "order processing": "order_processing",
    "order fulfillment": "order_fulfillment",
    "logistics": "logistics",
    "payroll": "payroll",
    "recruiting": "recruiting",
    "recruitment": "recruiting",
    "procurement": "procurement",
    "purchase order": "purchase_order",
    "spend analysis": "spend_analysis",
    "cloud migration": "cloud_migration",
    "database migration": "database_migration",
    "ci cd": "ci_cd",
    "deployment": "deployment",
    "code review": "code_review",
    "testing": "testing",
    "security operations": "security_operations",
    "incident response": "incident_response",
    "identity management": "identity_management",
    "access management": "access_management",
    "campaign management": "campaign_management",
    "content generation": "content_generation",
    "email marketing": "email_marketing",
    "social media": "social_media",
    "lead scoring": "lead_scoring",
    "personalization": "personalization",
    "analytics reporting": "analytics_reporting",
    "audit": "audit",
    "compliance monitoring": "compliance_monitoring",
    "regulatory reporting": "regulatory_reporting",
    "policy management": "policy_management",
    "data privacy": "data_privacy",
    "risk assessment": "risk_assessment",
    "discovery": "discovery",
    "quality control": "quality_control",
    "scheduling": "scheduling",
    "forecasting": "forecasting",
    "budgeting": "budgeting",
    "reconciliation": "reconciliation",
    "general ledger": "general_ledger",
    "tax preparation": "tax_preparation",
    "fixed assets": "fixed_assets",
    "benefits administration": "benefits_administration",
    "performance management": "performance_management",
    "learning development": "learning_development",
    "employee engagement": "employee_engagement",
    "compliance training": "compliance_training",
    "change management": "change_management",
    "asset management": "asset_management",
    "backup recovery": "backup_recovery",
    "network management": "network_management",
    "capacity planning": "capacity_planning",
    "performance optimization": "performance_optimization",
    "api management": "api_management",
    "requirements management": "requirements_management",
    "roadmap planning": "roadmap_planning",
    "user research": "user_research",
    "a b testing": "a_b_testing",
    "prototyping": "prototyping",
    "user testing": "user_testing",
    "accessibility": "accessibility",
    "design handoff": "design_handoff",
    "literature review": "literature_review",
    "experiment design": "experiment_design",
    "data collection": "data_collection",
    "statistical analysis": "statistical_analysis",
    "publication": "publication",
    "vendor selection": "vendor_selection",
    "contract negotiation": "contract_negotiation",
    "supplier evaluation": "supplier_evaluation",
    "route planning": "scheduling",
    "quality assurance": "quality_assurance",
    "sentiment analysis": "sentiment_analysis",
}

# Ordered keyword → canonical slug. LONGEST keywords first so
# "customer service call handling" hits call_routing before "customer".
WORKFLOW_KEYWORDS: list[tuple[str, str]] = [
    # finance / accounting
    ("invoic", "invoice_processing"),
    ("accounts payable", "accounts_payable"),
    ("accounts receivable", "accounts_receivable"),
    ("financial close", "financial_reporting"),
    ("financial reporting", "financial_reporting"),
    ("month end close", "financial_reporting"),
    ("revenue recognition", "revenue_recognition"),
    ("expense", "expense_management"),
    ("reconcil", "reconciliation"),
    ("general ledger", "general_ledger"),
    ("tax", "tax_preparation"),
    ("payroll", "payroll"),
    ("budget", "budgeting"),
    ("forecast", "forecasting"),
    ("audit", "audit"),
    ("fraud detection", "risk_assessment"),
    ("risk assessment", "risk_assessment"),
    ("risk management", "risk_assessment"),
    # sales / legal
    ("lead qualif", "lead_qualification"),
    ("lead generation", "lead_qualification"),
    ("proposal", "proposal_generation"),
    ("rfp", "proposal_generation"),
    ("quoting", "proposal_generation"),
    ("contract review", "contract_review"),
    ("contract", "contract_management"),
    ("litigation", "discovery"),
    ("legal", "contract_review"),
    ("compliance", "compliance_monitoring"),
    ("regulatory", "regulatory_reporting"),
    ("policy", "policy_management"),
    ("privacy", "data_privacy"),
    ("intellectual property", "intellectual_property"),
    # customer support
    ("customer service call", "call_routing"),
    ("call handling", "call_routing"),
    ("call center", "call_routing"),
    ("ticket", "ticketing"),
    ("helpdesk", "helpdesk"),
    ("help desk", "helpdesk"),
    ("support", "ticketing"),
    ("customer care", "call_routing"),
    ("knowledge management", "knowledge_base"),
    ("knowledge base", "knowledge_base"),
    ("self service", "self_service"),
    ("chatbot", "chat"),
    ("conversational", "chat"),
    ("sentiment", "sentiment_analysis"),
    ("quality assurance", "quality_assurance"),
    ("merchant support", "ticketing"),
    # HR
    ("onboard", "onboarding"),
    ("recruit", "recruiting"),
    ("hiring", "recruiting"),
    ("personnel file", "onboarding"),
    ("hr document", "onboarding"),
    ("benefits", "benefits_administration"),
    ("performance review", "performance_management"),
    ("performance management", "performance_management"),
    ("learning", "learning_development"),
    ("training", "learning_development"),
    ("engagement", "employee_engagement"),
    ("workforce", "employee_engagement"),
    # operations / supply chain
    ("warehouse", "warehouse_management"),
    ("inventory", "inventory_management"),
    ("supply chain", "supplier_management"),
    ("supplier", "supplier_management"),
    ("procure", "procurement"),
    ("purchase order", "purchase_order"),
    ("vendor selection", "vendor_selection"),
    ("spend", "spend_analysis"),
    ("order management", "order_processing"),
    ("order fulfillment", "order_fulfillment"),
    ("fulfillment", "order_fulfillment"),
    ("logistic", "logistics"),
    ("route plan", "scheduling"),
    ("route optimization", "scheduling"),
    ("scheduling", "scheduling"),
    ("dispatch", "scheduling"),
    ("quality control", "quality_control"),
    ("facilities", "facilities_management"),
    # IT / engineering
    ("cloud migration", "cloud_migration"),
    ("migration", "database_migration"),
    ("database", "database_migration"),
    ("ci cd", "ci_cd"),
    ("deployment", "deployment"),
    ("code review", "code_review"),
    ("testing", "testing"),
    ("test automation", "testing"),
    ("security", "security_operations"),
    ("incident", "incident_response"),
    ("identity", "identity_management"),
    ("access management", "access_management"),
    ("device provisioning", "asset_management"),
    ("asset", "asset_management"),
    ("infrastructure", "infrastructure_monitoring"),
    ("monitoring", "infrastructure_monitoring"),
    ("backup", "backup_recovery"),
    ("network", "network_management"),
    ("capacity", "capacity_planning"),
    ("performance optim", "performance_optimization"),
    ("api", "api_management"),
    ("mobile app", "prototyping"),
    ("software development", "code_review"),
    ("data pipeline", "data_collection"),
    # marketing / product
    ("campaign", "campaign_management"),
    ("brand campaign", "campaign_management"),
    ("content", "content_generation"),
    ("seo", "seo_optimization"),
    ("social media", "social_media"),
    ("email market", "email_marketing"),
    ("lead scoring", "lead_scoring"),
    ("personaliz", "personalization"),
    ("analytics", "analytics_reporting"),
    ("recommendation", "personalization"),
    ("visual search", "personalization"),
    ("product discovery", "user_research"),
    ("user research", "user_research"),
    ("requirements", "requirements_management"),
    ("roadmap", "roadmap_planning"),
    ("a b test", "a_b_testing"),
    ("prototyp", "prototyping"),
    ("user testing", "user_testing"),
    # research
    ("literature", "literature_review"),
    ("experiment", "experiment_design"),
    ("research", "literature_review"),
    ("statistical", "statistical_analysis"),
]

_ALIAS_LOOKUP: dict[str, str] = {_clean(k): v for k, v in WORKFLOW_ALIASES.items()}


def _best_keyword_match(cleaned: str) -> Optional[tuple[str, float]]:
    """Earliest keyword occurrence wins; ties break to the longest keyword."""
    best: Optional[tuple[tuple, str]] = None
    for keyword, slug in WORKFLOW_KEYWORDS:
        idx = cleaned.find(keyword)
        if idx >= 0:
            key = (idx, -len(keyword))
            if best is None or key < best[0]:
                best = (key, slug)
    if best:
        return best[1], 0.6
    return None


def normalize_workflow(raw: str) -> NormalizedValue:
    """Normalize a free-text workflow string onto a canonical slug."""
    if not raw or not str(raw).strip():
        return NormalizedValue(raw="", value="", source="workflow_taxonomy", confidence=0.0,
                               version=WORKFLOW_NORMALIZATION_VERSION)
    raw_s = str(raw).strip()
    cleaned = _clean(raw_s)

    canonical = _ALIAS_LOOKUP.get(cleaned)
    if canonical:
        return NormalizedValue(raw=raw_s, value=canonical, source="workflow_taxonomy",
                               method="explicit", confidence=1.0,
                               version=WORKFLOW_NORMALIZATION_VERSION)

    matched = _best_keyword_match(cleaned)
    if matched:
        slug, conf = matched
        return NormalizedValue(raw=raw_s, value=slug, source="workflow_taxonomy",
                               method="inferred", confidence=conf,
                               version=WORKFLOW_NORMALIZATION_VERSION)

    # Unmapped — keep the slugified raw value (never drop).
    return NormalizedValue(raw=raw_s, value=slugify(raw_s), source="workflow_taxonomy",
                           method="inferred", confidence=0.3,
                           version=WORKFLOW_NORMALIZATION_VERSION)


def infer_workflow(text: Optional[str]) -> NormalizedValue:
    """Infer a workflow from arbitrary text (title/problem statement)."""
    if not text:
        return NormalizedValue(raw="", value="", source="workflow_taxonomy", confidence=0.0,
                               version=WORKFLOW_NORMALIZATION_VERSION)
    cleaned = _clean(text)
    if not cleaned:
        return infer_workflow(None)
    matched = _best_keyword_match(cleaned)
    if matched:
        slug, _conf = matched
        return NormalizedValue(raw=text[:200], value=slug, source="workflow_taxonomy",
                               method="inferred", confidence=0.5,
                               version=WORKFLOW_NORMALIZATION_VERSION)
    return NormalizedValue(raw=text[:200], value="uncategorized", source="workflow_taxonomy",
                           method="inferred", confidence=0.2,
                           version=WORKFLOW_NORMALIZATION_VERSION)


def is_canonical(slug: Optional[str]) -> bool:
    return slug in ALL_WORKFLOWS
