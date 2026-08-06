"""Canonical vendor and technology taxonomies.

Phase 4 — the canonical knowledge layer for the implementation evidence
graph. Mirrors ``organization/taxonomy.py`` conventions: deterministic
normalization, raw values preserved, provenance attached, equivalent labels
map onto one canonical key.

Two dimensions:

  * **Vendors** — the company providing the implementation/software
    (Oracle, UiPath, AWS, ...). Canonical key = snake_case vendor name.
  * **Technologies** — the software products/platforms used in the
    intervention (Jira, BigQuery, UiPath Maestro, ...). Normalizes to a
    canonical **product family** key and exposes the product's **family**
    (collaboration, rpa, data_warehouse, ...) for diversity analytics.

Design rules (from taxonomy.py):
  * Everything is deterministic — same input, same output.
  * Raw values are preserved; normalized values carry provenance.
  * Equivalent labels normalize consistently (AWS, Amazon Web Services,
    Amazon Web Services (AWS) → aws).
  * Legal suffixes (Inc, LLC, Corp, Ltd), trademarks (®, ™) and parenthetical
    annotations are stripped before matching.
"""

from __future__ import annotations

import re
from typing import Optional

from compass_collector.organization.taxonomy import NormalizedValue

VENDOR_NORMALIZATION_VERSION = "vendor-v1"
TECH_NORMALIZATION_VERSION = "tech-v1"

# ---------------------------------------------------------------------------
# Canonical vendor taxonomy: key → label
# ---------------------------------------------------------------------------

CANONICAL_VENDORS: dict[str, str] = {
    # Cloud / infrastructure
    "aws": "Amazon Web Services",
    "google_cloud": "Google Cloud",
    "microsoft": "Microsoft",
    "oracle": "Oracle",
    "ibm": "IBM",
    "sap": "SAP",
    "salesforce": "Salesforce",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "red_hat": "Red Hat",
    "nvidia": "NVIDIA",
    "cloudflare": "Cloudflare",
    "netflix": "Netflix",
    "elastic": "Elastic",
    # Automation / RPA / AI
    "uipath": "UiPath",
    "automation_anywhere": "Automation Anywhere",
    "blue_prism": "SS&C Blue Prism",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "immix": "Immix",
    "nividous": "Nividous",
    "whatfix": "Whatfix",
    "parascript": "Parascript",
    "hyperscience": "Hyperscience",
    "abbeyy": "ABBYY",
    "kofax": "Kofax",
    "mitek": "Mitek Systems",
    # Collaboration / productivity / customer
    "atlassian": "Atlassian",
    "slack": "Slack",
    "zendesk": "Zendesk",
    "adobe": "Adobe",
    "loom": "Loom",
    "rovo": "Atlassian Rovo",
    # Consulting / SI
    "accenture": "Accenture",
    "deloitte": "Deloitte",
    "mckinsey": "McKinsey",
    "bcg": "BCG",
    "kpmg": "KPMG",
    "pwc": "PwC",
    "bain": "Bain & Company",
    "ey": "EY",
    "devoteam": "Devoteam",
    "calfus": "Calfus",
    "appinventiv": "Appinventiv",
    "ninetwothree": "NineTwoThree",
    "office_samurai": "Office Samurai",
    "adaptavist": "Adaptavist",
    "answerthink": "Answerthink",
    "egen": "Egen",
    "meegle": "Meegle",
    # Vertical / niche vendors present in the evidence graph
    "rad": "Robotic Assistance Devices (RAD)",
    "sara": "SARA (RAD)",
    "omnicell": "Omnicell",
    "athenahealth": "athenahealth",
    "hologic": "Hologic",
    "omniq": "OMNIQ",
    "logility": "Logility",
    "fieldroutes": "FieldRoutes",
    "homecare_homebase": "HomeCare HomeBase",
    "northern_trust": "Northern Trust",
    "paradigm": "Paradigm",
    "cyborg": "Cyborg",
    "hyperion": "Hyperion",
    "rio_mini": "RIO Mini",
    "afi_labs": "Afi Labs",
}

# Alias map: normalized phrase → canonical vendor key.
# Keys are pre-normalized with _vendor_key (lower, separators → space).
VENDOR_ALIASES: dict[str, str] = {
    # AWS family
    "aws": "aws",
    "amazon web services": "aws",
    "amazon": "aws",
    "amazon aws": "aws",
    # Google family
    "google cloud": "google_cloud",
    "google cloud platform": "google_cloud",
    "gcp": "google_cloud",
    "google": "google_cloud",
    # Microsoft
    "microsoft": "microsoft",
    "microsoft azure": "microsoft",
    "azure": "microsoft",
    # Oracle
    "oracle": "oracle",
    "oracle consulting": "oracle",
    "oracle corporation": "oracle",
    # IBM
    "ibm": "ibm",
    "ibm watson": "ibm",
    "ibm cloud": "ibm",
    # SAP
    "sap": "sap",
    "sap se": "sap",
    # Salesforce
    "salesforce": "salesforce",
    "salesforce inc": "salesforce",
    # Automation
    "uipath": "uipath",
    "ui path": "uipath",
    "automation anywhere": "automation_anywhere",
    "automationanywhere": "automation_anywhere",
    "ss&c blue prism": "blue_prism",
    "blue prism": "blue_prism",
    "immix": "immix",
    "nividous": "nividous",
    "whatfix": "whatfix",
    "parascript": "parascript",
    "parascript llc": "parascript",
    "hyperscience": "hyperscience",
    "kofax": "kofax",
    "mitek systems": "mitek",
    "mitek": "mitek",
    # AI vendors
    "openai": "openai",
    "anthropic": "anthropic",
    "amazon bedrock": "aws",
    "snowflake cortex ai": "snowflake",
    "gemini": "gemini",
    "google gemini": "gemini",
    # Collaboration / productivity
    "atlassian": "atlassian",
    "slack": "slack",
    "slack salesforce": "slack",
    "zendesk": "zendesk",
    "adobe": "adobe",
    "loom": "loom",
    "rovo": "rovo",
    # Consulting / SI
    "accenture": "accenture",
    "deloitte": "deloitte",
    "mckinsey": "mckinsey",
    "mckinsey & company": "mckinsey",
    "bcg": "bcg",
    "boston consulting group": "bcg",
    "kpmg": "kpmg",
    "pwc": "pwc",
    "pwc uk": "pwc",
    "pricewaterhousecoopers": "pwc",
    "bain": "bain",
    "bain & company": "bain",
    "ey": "ey",
    "ernst & young": "ey",
    "devoteam": "devoteam",
    "devoteam netherlands": "devoteam",
    "calfus": "calfus",
    "appinventiv": "appinventiv",
    "ninetwothree": "ninetwothree",
    "nine two three": "ninetwothree",
    "office samurai": "office_samurai",
    "adaptavist": "adaptavist",
    "answerthink": "answerthink",
    "egen": "egen",
    "meegle": "meegle",
    # Vertical / niche
    "rad": "rad",
    "robotic assistance devices": "rad",
    "sara": "sara",
    "omnicell": "omnicell",
    "athenahealth": "athenahealth",
    "hologic": "hologic",
    "omniq": "omniq",
    "logility": "logility",
    "fieldroutes": "fieldroutes",
    "homecare homebase": "homecare_homebase",
    "northern trust": "northern_trust",
    "paradigm": "paradigm",
    "cyborg": "cyborg",
    "hyperion": "hyperion",
    "rio mini": "rio_mini",
    "afi labs": "afi_labs",
    "servicenow": "servicenow",
    "service now": "servicenow",
    "workday": "workday",
    "zapier": "zapier",
    "miro": "miro",
    "lattice": "lattice",
}

# Keyword → vendor key for fuzzy/prefix matching (confidence 0.7). Most
# specific keywords first; ordering matters (first match wins per part).
VENDOR_KEYWORDS: list[tuple[str, str]] = [
    ("uipath", "uipath"),
    ("automation anywhere", "automation_anywhere"),
    ("blue prism", "blue_prism"),
    ("amazon web services", "aws"),
    ("aws", "aws"),
    ("amazon", "aws"),
    ("nvidia", "nvidia"),
    ("red hat", "red_hat"),
    ("elastic", "elastic"),
    ("cloudflare", "cloudflare"),
    ("netflix", "netflix"),
    ("rosa", "rad"),
    ("google cloud", "google_cloud"),
    ("google", "google_cloud"),
    ("microsoft", "microsoft"),
    ("salesforce", "salesforce"),
    ("oracle", "oracle"),
    ("ibm", "ibm"),
    ("atlassian", "atlassian"),
    ("zendesk", "zendesk"),
    ("slack", "slack"),
    ("adobe", "adobe"),
    ("snowflake", "snowflake"),
    ("databricks", "databricks"),
    ("openai", "openai"),
    ("anthropic", "anthropic"),
    ("accenture", "accenture"),
    ("deloitte", "deloitte"),
    ("mckinsey", "mckinsey"),
    ("kpmg", "kpmg"),
    ("pwc", "pwc"),
    ("immix", "immix"),
    ("nividous", "nividous"),
    ("whatfix", "whatfix"),
    ("parascript", "parascript"),
    ("hyperscience", "hyperscience"),
    ("kofax", "kofax"),
    ("mitek", "mitek"),
    ("robotic assistance devices", "rad"),
    ("sara", "sara"),
    ("omnicell", "omnicell"),
    ("athenahealth", "athenahealth"),
    ("hologic", "hologic"),
    ("omniq", "omniq"),
    ("logility", "logility"),
    ("fieldroutes", "fieldroutes"),
    ("homecare homebase", "homecare_homebase"),
    ("northern trust", "northern_trust"),
    ("appinventiv", "appinventiv"),
    ("devoteam", "devoteam"),
    ("calfus", "calfus"),
]

_VENDOR_KEY_RE = re.compile(r"[^a-z0-9]+")
# Legal/org suffixes only — NOT product words like "service"/"software"/"cloud",
# which are part of technology product names (Jira Service Management, etc.).
_VENDOR_FILLER_RE = re.compile(
    r"\b(the|and|inc|corp|co|company|llc|ltd|plc|gmbh|ag|group|holdings?|"
    r"limited|llp|pte)\b\.?",
    re.IGNORECASE,
)
_TRADEMARK_RE = re.compile(r"[\u00ae\u2122\u00a9]|\(r\)|\(tm\)", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")


def _vendor_key(raw: str) -> str:
    """Normalize a raw vendor string to a lookup key (separators → space)."""
    if raw is None:
        return ""
    text = str(raw).strip()
    text = _TRADEMARK_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    text = _VENDOR_FILLER_RE.sub(" ", text)
    text = _VENDOR_KEY_RE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def normalize_vendor(raw: str) -> NormalizedValue:
    """Normalize a raw vendor string onto a canonical vendor key."""
    if not raw or not str(raw).strip():
        return NormalizedValue(raw="", value="", source="vendor_taxonomy", confidence=0.0,
                               version=VENDOR_NORMALIZATION_VERSION)
    raw_s = str(raw).strip()
    key = _vendor_key(raw_s)

    canonical = _VENDOR_ALIAS_LOOKUP.get(key)
    if canonical:
        return NormalizedValue(raw=raw_s, value=canonical, source="vendor_taxonomy",
                               method="explicit", confidence=1.0,
                               version=VENDOR_NORMALIZATION_VERSION)

    # Fuzzy: contains a known keyword → inferred canonical vendor.
    for kw, vendor_key in VENDOR_KEYWORDS:
        if kw in key:
            return NormalizedValue(raw=raw_s, value=vendor_key, source="vendor_taxonomy",
                                   method="inferred", confidence=0.7,
                                   version=VENDOR_NORMALIZATION_VERSION)
    # Unmapped — keep raw as-is with low confidence (never drop the value).
    return NormalizedValue(raw=raw_s, value=key or raw_s, source="vendor_taxonomy",
                           method="inferred", confidence=0.3,
                           version=VENDOR_NORMALIZATION_VERSION)


def vendor_label(key: Optional[str]) -> Optional[str]:
    return CANONICAL_VENDORS.get(key or "") if key else None


# ---------------------------------------------------------------------------
# Canonical technology taxonomy: product family key → {label, family}
# ---------------------------------------------------------------------------

TECHNOLOGY_FAMILIES: dict[str, str] = {
    "collaboration": "Collaboration & Knowledge",
    "project_management": "Project & Work Management",
    "crm": "CRM & Sales",
    "customer_support": "Customer Support",
    "rpa": "Robotic Process Automation",
    "genai": "Generative AI",
    "ml": "Machine Learning & Analytics",
    "data_warehouse": "Data Warehousing & Lakehouse",
    "cloud_compute": "Cloud Compute & Infra",
    "kubernetes": "Kubernetes & Containers",
    "serverless": "Serverless",
    "erp": "ERP & Finance Systems",
    "hcm": "HCM & Workforce",
    "cms": "Content & Experience",
    "marketing": "Marketing Automation",
    "dev_tools": "Developer Tools & CI/CD",
    "document": "Document Processing",
    "identity": "Identity & Security",
    "video": "Video & Communications",
    "ecommerce": "E-commerce",
    "it_service": "IT Service Management",
    "data_integration": "Data Integration & ETL",
    "sap_erp": "SAP ERP",
    "document_automation": "Document Automation",
}

CANONICAL_TECHNOLOGIES: dict[str, dict] = {
    # Collaboration / knowledge
    "slack": {"label": "Slack", "family": "collaboration"},
    "confluence": {"label": "Confluence", "family": "collaboration"},
    "atlassian_cloud": {"label": "Atlassian Cloud Enterprise", "family": "collaboration"},
    "loom": {"label": "Loom", "family": "video"},
    "rovo": {"label": "Rovo", "family": "genai"},
    # Project / work management
    "jira": {"label": "Jira", "family": "project_management"},
    "jira_service_management": {"label": "Jira Service Management", "family": "it_service"},
    "jira_product_discovery": {"label": "Jira Product Discovery", "family": "project_management"},
    "atlassian_teamwork": {"label": "Atlassian Teamwork Collection", "family": "project_management"},
    "bitbucket": {"label": "Bitbucket", "family": "dev_tools"},
    "workfront": {"label": "Adobe Workfront", "family": "project_management"},
    # CRM / support
    "salesforce": {"label": "Salesforce", "family": "crm"},
    "salesforce_crm": {"label": "Salesforce CRM", "family": "crm"},
    "agentforce": {"label": "Agentforce", "family": "genai"},
    "zendesk": {"label": "Zendesk", "family": "customer_support"},
    "zendesk_suite": {"label": "Zendesk Suite", "family": "customer_support"},
    "zendesk_ai": {"label": "Zendesk AI", "family": "genai"},
    # RPA / automation
    "uipath": {"label": "UiPath", "family": "rpa"},
    "uipath_platform": {"label": "UiPath Platform", "family": "rpa"},
    "automation_anywhere": {"label": "Automation Anywhere", "family": "rpa"},
    "automation_360": {"label": "Automation 360", "family": "rpa"},
    # Generative AI
    "gemini": {"label": "Gemini", "family": "genai"},
    "gemini_enterprise": {"label": "Gemini Enterprise Agent Platform", "family": "genai"},
    "watsonx": {"label": "IBM watsonx", "family": "genai"},
    "bedrock": {"label": "Amazon Bedrock", "family": "genai"},
    "openai": {"label": "OpenAI", "family": "genai"},
    # ML / analytics
    "bigquery": {"label": "BigQuery", "family": "ml"},
    "model_garden": {"label": "Model Garden", "family": "ml"},
    "sagemaker": {"label": "Amazon SageMaker", "family": "ml"},
    # Data warehousing
    "snowflake": {"label": "Snowflake", "family": "data_warehouse"},
    "databricks": {"label": "Databricks", "family": "data_warehouse"},
    # Cloud infra
    "compute_engine": {"label": "Google Compute Engine", "family": "cloud_compute"},
    "gke": {"label": "Google Kubernetes Engine", "family": "kubernetes"},
    "cloud_run": {"label": "Cloud Run", "family": "serverless"},
    "eks": {"label": "Amazon EKS", "family": "kubernetes"},
    "ec2": {"label": "Amazon EC2", "family": "cloud_compute"},
    "s3": {"label": "Amazon S3", "family": "cloud_compute"},
    "lambda": {"label": "AWS Lambda", "family": "serverless"},
    "rds": {"label": "Amazon RDS", "family": "cloud_compute"},
    "oci": {"label": "Oracle Cloud Infrastructure", "family": "cloud_compute"},
    # ERP / HCM
    "oracle_fusion": {"label": "Oracle Fusion Cloud", "family": "erp"},
    "oracle_fusion_hcm": {"label": "Oracle Fusion Cloud HCM", "family": "hcm"},
    "oracle_fusion_epm": {"label": "Oracle Fusion Cloud EPM", "family": "erp"},
    "oracle_adw": {"label": "Oracle Autonomous Data Warehouse", "family": "data_warehouse"},
    "oracle_analytics": {"label": "Oracle Analytics", "family": "ml"},
    "oracle_cloud_epm": {"label": "Oracle Cloud EPM", "family": "erp"},
    "oracle_talent": {"label": "Oracle Talent Management", "family": "hcm"},
    "oracle_learning": {"label": "Oracle Learning", "family": "hcm"},
    "oracle_hr_helpdesk": {"label": "Oracle HR Help Desk", "family": "hcm"},
    "sap": {"label": "SAP S/4HANA", "family": "sap_erp"},
    "openshift": {"label": "Red Hat OpenShift", "family": "kubernetes"},
    "dataflow": {"label": "Google Dataflow", "family": "data_integration"},
    "snowflake_cortex": {"label": "Snowflake Cortex", "family": "genai"},
    "document_automation": {"label": "Document Automation", "family": "document_automation"},
    "vertex_ai": {"label": "Vertex AI", "family": "ml"},
    "dialogflow": {"label": "Dialogflow", "family": "genai"},
    "conversational_agents": {"label": "Google Conversational Agents", "family": "genai"},
    "adobe": {"label": "Adobe", "family": "cms"},
    "blue_prism": {"label": "SS&C Blue Prism", "family": "rpa"},
    "looker": {"label": "Google Looker", "family": "ml"},
    "alloydb": {"label": "Google AlloyDB", "family": "cloud_compute"},
    "bigtable": {"label": "Google Bigtable", "family": "cloud_compute"},
    "workspace": {"label": "Google Workspace", "family": "collaboration"},
    "notebooklm": {"label": "NotebookLM", "family": "genai"},
    "claude": {"label": "Anthropic Claude", "family": "genai"},
    # Adobe / content / marketing
    "adobe_commerce": {"label": "Adobe Commerce", "family": "ecommerce"},
    "marketo": {"label": "Adobe Marketo Engage", "family": "marketing"},
    "aem": {"label": "Adobe Experience Manager", "family": "cms"},
    "aem_sites": {"label": "Adobe Experience Manager Sites", "family": "cms"},
    "aem_assets": {"label": "Adobe Experience Manager Assets", "family": "cms"},
    "experience_cloud": {"label": "Adobe Experience Cloud", "family": "marketing"},
    "adobe_analytics": {"label": "Adobe Analytics", "family": "ml"},
    "adobe_target": {"label": "Adobe Target", "family": "marketing"},
    "acrobat_sign": {"label": "Adobe Acrobat Sign", "family": "document"},
    "acrobat_services": {"label": "Adobe Acrobat Services APIs", "family": "document"},
    "learning_manager": {"label": "Adobe Learning Manager", "family": "hcm"},
}

# Alias map: normalized phrase → technology key.
TECH_ALIASES: dict[str, str] = {
    "slack": "slack",
    "jira": "jira",
    "jira service management": "jira_service_management",
    "jira product discovery": "jira_product_discovery",
    "confluence": "confluence",
    "bitbucket": "bitbucket",
    "bigquery": "bigquery",
    "automation anywhere": "automation_anywhere",
    "automation 360": "automation_360",
    "rovo": "rovo",
    "gemini": "gemini",
    "gemini enterprise": "gemini_enterprise",
    "gemini enterprise agent platform": "gemini_enterprise",
    "salesforce": "salesforce",
    "salesforce crm": "salesforce_crm",
    "agentforce": "agentforce",
    "adobe commerce": "adobe_commerce",
    "adobe marketo engage": "marketo",
    "marketo": "marketo",
    "adobe experience manager": "aem",
    "adobe experience manager sites": "aem_sites",
    "adobe experience manager assets": "aem_assets",
    "adobe experience cloud": "experience_cloud",
    "adobe analytics": "adobe_analytics",
    "adobe target": "adobe_target",
    "adobe workfront": "workfront",
    "adobe acrobat sign": "acrobat_sign",
    "adobe acrobat services apis": "acrobat_services",
    "adobe learning manager": "learning_manager",
    "jira service management": "jira_service_management",
    "loom": "loom",
    "zendesk": "zendesk",
    "zendesk suite": "zendesk_suite",
    "zendesk ai": "zendesk_ai",
    "compute engine": "compute_engine",
    "google compute engine": "compute_engine",
    "google kubernetes engine": "gke",
    "cloud run": "cloud_run",
    "amazon sagemaker": "sagemaker",
    "amazon bedrock": "bedrock",
    "model garden": "model_garden",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "oracle fusion cloud hcm": "oracle_fusion_hcm",
    "oracle fusion cloud epm": "oracle_fusion_epm",
    "oracle fusion cloud": "oracle_fusion",
    "oracle autonomous data warehouse": "oracle_adw",
    "oracle analytics": "oracle_analytics",
    "oracle cloud infrastructure": "oci",
    "oracle cloud epm": "oracle_cloud_epm",
    "oracle talent management": "oracle_talent",
    "oracle learning": "oracle_learning",
    "oracle hr help desk": "oracle_hr_helpdesk",
    "ibm watsonx ai": "watsonx",
    "ibm watsonx orchestrator": "watsonx",
    "ibm watsonx": "watsonx",
    "atlassian cloud enterprise": "atlassian_cloud",
    "atlassian teamwork collection": "atlassian_teamwork",
    "atlassian guard": "atlassian_cloud",
    "amazon elastic kubernetes service": "eks",
    "amazon eks": "eks",
    "amazon ec2": "ec2",
    "amazon s3": "s3",
    "aws lambda": "lambda",
    "amazon rds": "rds",
    "sap s 4hana": "sap",
    "sap": "sap",
    "openshift": "openshift",
    "red hat openshift": "openshift",
    "dataflow": "dataflow",
    "google dataflow": "dataflow",
    "cortex": "snowflake_cortex",
    "document automation": "document_automation",
    "uipath": "uipath",
    "uipath platform": "uipath_platform",
}

# Keyword → technology key for prefix/fuzzy matching (0.7). Order matters.
TECH_KEYWORDS: list[tuple[str, str]] = [
    ("uipath", "uipath"),
    ("automation anywhere", "automation_anywhere"),
    ("automation 360", "automation_360"),
    ("blue prism", "blue_prism"),
    ("looker", "looker"),
    ("alloydb", "alloydb"),
    ("bigtable", "bigtable"),
    ("workspace", "workspace"),
    ("notebooklm", "notebooklm"),
    ("claude", "claude"),
    ("jira service management", "jira_service_management"),
    ("jira product discovery", "jira_product_discovery"),
    ("jira", "jira"),
    ("confluence", "confluence"),
    ("bitbucket", "bitbucket"),
    ("slack", "slack"),
    ("bigquery", "bigquery"),
    ("gemini enterprise", "gemini_enterprise"),
    ("gemini", "gemini"),
    ("agentforce", "agentforce"),
    ("salesforce crm", "salesforce_crm"),
    ("salesforce", "salesforce"),
    ("zendesk", "zendesk"),
    ("adobe marketo", "marketo"),
    ("marketo", "marketo"),
    ("adobe commerce", "adobe_commerce"),
    ("experience manager", "aem"),
    ("experience cloud", "experience_cloud"),
    ("adobe analytics", "adobe_analytics"),
    ("adobe target", "adobe_target"),
    ("workfront", "workfront"),
    ("adobe acrobat", "acrobat_services"),
    ("acrobat sign", "acrobat_sign"),
    ("adobe learning", "learning_manager"),
    ("adobe", "aem"),
    ("loom", "loom"),
    ("compute engine", "compute_engine"),
    ("kubernetes engine", "gke"),
    ("cloud run", "cloud_run"),
    ("sagemaker", "sagemaker"),
    ("bedrock", "bedrock"),
    ("model garden", "model_garden"),
    ("snowflake", "snowflake"),
    ("databricks", "databricks"),
    ("oracle fusion", "oracle_fusion"),
    ("oracle autonomous", "oracle_adw"),
    ("oracle analytics", "oracle_analytics"),
    ("oracle cloud", "oci"),
    ("oracle talent", "oracle_talent"),
    ("oracle learning", "oracle_learning"),
    ("oracle hr", "oracle_hr_helpdesk"),
    ("oracle", "oracle_fusion"),
    ("watsonx", "watsonx"),
    ("atlassian", "atlassian_cloud"),
    ("amazon elastic kubernetes", "eks"),
    ("amazon ec2", "ec2"),
    ("amazon s3", "s3"),
    ("aws lambda", "lambda"),
    ("amazon rds", "rds"),
    ("amazon", "bedrock"),
    ("s 4hana", "sap"),
    ("sap", "sap"),
    ("openshift", "openshift"),
    ("dataflow", "dataflow"),
    ("cortex", "snowflake_cortex"),
    ("document automation", "document_automation"),
    ("vertex", "vertex_ai"),
    ("dialogflow", "dialogflow"),
    ("conversational agents", "conversational_agents"),
    ("persistent disk", "compute_engine"),
    ("hyperdisk", "compute_engine"),
    ("automation co pilot", "uipath"),
    ("rovo", "rovo"),
]

_TECH_KEY_RE = re.compile(r"[^a-z0-9]+")


def _tech_key(raw: str) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    text = _TRADEMARK_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    text = _VENDOR_FILLER_RE.sub(" ", text)
    text = _TECH_KEY_RE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


# Lookups keyed by the SAME key function used at match time (import-time build).
_VENDOR_ALIAS_LOOKUP: dict[str, str] = {_vendor_key(k): v for k, v in VENDOR_ALIASES.items()}
_TECH_ALIAS_LOOKUP: dict[str, str] = {_tech_key(k): v for k, v in TECH_ALIASES.items()}


def normalize_technology(raw: str) -> NormalizedValue:
    """Normalize a raw technology/product string onto a canonical family key."""
    if not raw or not str(raw).strip():
        return NormalizedValue(raw="", value="", source="tech_taxonomy", confidence=0.0,
                               version=TECH_NORMALIZATION_VERSION)
    raw_s = str(raw).strip()
    key = _tech_key(raw_s)

    canonical = _TECH_ALIAS_LOOKUP.get(key)
    if canonical:
        return NormalizedValue(raw=raw_s, value=canonical, source="tech_taxonomy",
                               method="explicit", confidence=1.0,
                               version=TECH_NORMALIZATION_VERSION)

    for kw, tech_key in TECH_KEYWORDS:
        if kw in key:
            return NormalizedValue(raw=raw_s, value=tech_key, source="tech_taxonomy",
                                   method="inferred", confidence=0.7,
                                   version=TECH_NORMALIZATION_VERSION)

    return NormalizedValue(raw=raw_s, value=key or raw_s, source="tech_taxonomy",
                           method="inferred", confidence=0.3,
                           version=TECH_NORMALIZATION_VERSION)


def technology_family(key: Optional[str]) -> Optional[str]:
    entry = CANONICAL_TECHNOLOGIES.get(key or "")
    return entry["family"] if entry else None


def technology_label(key: Optional[str]) -> Optional[str]:
    entry = CANONICAL_TECHNOLOGIES.get(key or "")
    return entry["label"] if entry else None
