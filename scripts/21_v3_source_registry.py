#!/usr/bin/env python3
"""V3: Seed the persistent source registry with high-value implementation sources."""

import json, os, uuid
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
REGISTRY_PATH = BASE / "data" / "source_registry.json"

SOURCES = [
    # ── Cloud Platforms ──
    {"org": "Amazon", "source_name": "AWS Customer Stories", "base_url": "https://aws.amazon.com/solutions/case-studies/", "crawler_type": "sitemap", "discovery_url": "https://aws.amazon.com/solutions/case-studies/", "sitemap": "https://aws.amazon.com/solutions/case-studies/sitemap.xml", "rss": "", "category": "cloud", "priority": 1, "enabled": True},
    {"org": "Microsoft", "source_name": "Microsoft Customer Stories", "base_url": "https://customers.microsoft.com/", "crawler_type": "sitemap", "discovery_url": "https://customers.microsoft.com/", "sitemap": "https://customers.microsoft.com/sitemap.xml", "rss": "", "category": "cloud", "priority": 1, "enabled": True},
    {"org": "Google", "source_name": "Google Cloud Customer Stories", "base_url": "https://cloud.google.com/customers", "crawler_type": "sitemap", "discovery_url": "https://cloud.google.com/customers", "sitemap": "https://cloud.google.com/customers/sitemap.xml", "rss": "", "category": "cloud", "priority": 1, "enabled": True},
    {"org": "Oracle", "source_name": "Oracle Customer Stories", "base_url": "https://www.oracle.com/customers/", "crawler_type": "sitemap", "discovery_url": "https://www.oracle.com/customers/", "sitemap": "", "rss": "", "category": "cloud", "priority": 2, "enabled": True},
    {"org": "IBM", "source_name": "IBM Customer Stories", "base_url": "https://www.ibm.com/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.ibm.com/case-studies", "sitemap": "", "rss": "", "category": "cloud", "priority": 2, "enabled": True},
    {"org": "SAP", "source_name": "SAP Customer Stories", "base_url": "https://www.sap.com/customer-stories.html", "crawler_type": "sitemap", "discovery_url": "https://www.sap.com/customer-stories.html", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Snowflake", "source_name": "Snowflake Customer Stories", "base_url": "https://www.snowflake.com/customers/", "crawler_type": "sitemap", "discovery_url": "https://www.snowflake.com/customers/", "sitemap": "", "rss": "", "category": "cloud", "priority": 2, "enabled": True},
    {"org": "Databricks", "source_name": "Databricks Customer Stories", "base_url": "https://www.databricks.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.databricks.com/customers", "sitemap": "", "rss": "", "category": "cloud", "priority": 2, "enabled": True},

    # ── AI Vendors ──
    {"org": "OpenAI", "source_name": "OpenAI Customer Stories", "base_url": "https://openai.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://openai.com/customer-stories", "sitemap": "", "rss": "", "category": "ai_vendor", "priority": 1, "enabled": True},
    {"org": "Anthropic", "source_name": "Anthropic Customer Stories", "base_url": "https://www.anthropic.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://www.anthropic.com/customer-stories", "sitemap": "", "rss": "", "category": "ai_vendor", "priority": 1, "enabled": True},
    {"org": "Microsoft", "source_name": "Microsoft Copilot Customer Stories", "base_url": "https://www.microsoft.com/en-us/microsoft-copilot/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://www.microsoft.com/en-us/microsoft-copilot/customer-stories", "sitemap": "", "rss": "", "category": "ai_vendor", "priority": 1, "enabled": True},
    {"org": "UiPath", "source_name": "UiPath Case Studies", "base_url": "https://www.uipath.com/resources/automation-case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.uipath.com/resources/automation-case-studies", "sitemap": "", "rss": "", "category": "automation", "priority": 1, "enabled": True},
    {"org": "Automation Anywhere", "source_name": "Automation Anywhere Case Studies", "base_url": "https://www.automationanywhere.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.automationanywhere.com/customers", "sitemap": "", "rss": "", "category": "automation", "priority": 2, "enabled": True},
    {"org": "Blue Prism", "source_name": "Blue Prism Customer Stories", "base_url": "https://www.blueprism.com/customers/", "crawler_type": "sitemap", "discovery_url": "https://www.blueprism.com/customers/", "sitemap": "", "rss": "", "category": "automation", "priority": 2, "enabled": True},
    {"org": "ServiceNow", "source_name": "ServiceNow Customer Stories", "base_url": "https://www.servicenow.com/customers/", "crawler_type": "sitemap", "discovery_url": "https://www.servicenow.com/customers/", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 1, "enabled": True},
    {"org": "Salesforce", "source_name": "Salesforce Customer Success", "base_url": "https://www.salesforce.com/customer-success-stories/", "crawler_type": "sitemap", "discovery_url": "https://www.salesforce.com/customer-success-stories/", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 1, "enabled": True},
    {"org": "Zendesk", "source_name": "Zendesk Customer Stories", "base_url": "https://www.zendesk.com/customer-stories/", "crawler_type": "sitemap", "discovery_url": "https://www.zendesk.com/customer-stories/", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},

    # ── Business Software ──
    {"org": "HubSpot", "source_name": "HubSpot Customer Stories", "base_url": "https://www.hubspot.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.hubspot.com/customers", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Atlassian", "source_name": "Atlassian Customer Stories", "base_url": "https://www.atlassian.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.atlassian.com/customers", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Slack", "source_name": "Slack Customer Stories", "base_url": "https://slack.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://slack.com/customer-stories", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Workday", "source_name": "Workday Customer Stories", "base_url": "https://www.workday.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://www.workday.com/customer-stories", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Notion", "source_name": "Notion Customer Stories", "base_url": "https://www.notion.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.notion.com/customers", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},
    {"org": "Asana", "source_name": "Asana Customer Stories", "base_url": "https://asana.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://asana.com/customer-stories", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},
    {"org": "Monday.com", "source_name": "Monday.com Customer Stories", "base_url": "https://monday.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://monday.com/customer-stories", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},
    {"org": "Cisco", "source_name": "Cisco Customer Case Studies", "base_url": "https://www.cisco.com/c/en/us/solutions/customer-case-studies.html", "crawler_type": "sitemap", "discovery_url": "https://www.cisco.com/c/en/us/solutions/customer-case-studies.html", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Adobe", "source_name": "Adobe Customer Stories", "base_url": "https://business.adobe.com/customer-success-stories/", "crawler_type": "sitemap", "discovery_url": "https://business.adobe.com/customer-success-stories/", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 2, "enabled": True},
    {"org": "Dropbox", "source_name": "Dropbox Customer Stories", "base_url": "https://www.dropbox.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.dropbox.com/customers", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},
    {"org": "Box", "source_name": "Box Customer Stories", "base_url": "https://www.box.com/customers", "crawler_type": "sitemap", "discovery_url": "https://www.box.com/customers", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},
    {"org": "Zoom", "source_name": "Zoom Customer Stories", "base_url": "https://www.zoom.com/customer-stories", "crawler_type": "sitemap", "discovery_url": "https://www.zoom.com/customer-stories", "sitemap": "", "rss": "", "category": "enterprise_software", "priority": 3, "enabled": True},

    # ── Consulting Firms ──
    {"org": "McKinsey", "source_name": "McKinsey Operations Insights", "base_url": "https://www.mckinsey.com/capabilities/operations/our-insights", "crawler_type": "rss", "discovery_url": "https://www.mckinsey.com/capabilities/operations/our-insights", "sitemap": "", "rss": "https://www.mckinsey.com/feed", "category": "consulting", "priority": 1, "enabled": True},
    {"org": "BCG", "source_name": "BCG Publications", "base_url": "https://www.bcg.com/publications", "crawler_type": "rss", "discovery_url": "https://www.bcg.com/publications", "sitemap": "", "rss": "https://www.bcg.com/feed", "category": "consulting", "priority": 1, "enabled": True},
    {"org": "Bain", "source_name": "Bain Insights", "base_url": "https://www.bain.com/insights/", "crawler_type": "rss", "discovery_url": "https://www.bain.com/insights/", "sitemap": "", "rss": "", "category": "consulting", "priority": 2, "enabled": True},
    {"org": "Deloitte", "source_name": "Deloitte Insights", "base_url": "https://www.deloitte.com/insights/", "crawler_type": "rss", "discovery_url": "https://www.deloitte.com/insights/", "sitemap": "", "rss": "", "category": "consulting", "priority": 1, "enabled": True},
    {"org": "Accenture", "source_name": "Accenture Case Studies", "base_url": "https://www.accenture.com/us-en/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.accenture.com/us-en/case-studies", "sitemap": "", "rss": "", "category": "consulting", "priority": 1, "enabled": True},
    {"org": "PwC", "source_name": "PwC Case Studies", "base_url": "https://www.pwc.com/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.pwc.com/case-studies", "sitemap": "", "rss": "", "category": "consulting", "priority": 2, "enabled": True},
    {"org": "EY", "source_name": "EY Case Studies", "base_url": "https://www.ey.com/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.ey.com/case-studies", "sitemap": "", "rss": "", "category": "consulting", "priority": 2, "enabled": True},
    {"org": "KPMG", "source_name": "KPMG Case Studies", "base_url": "https://kpmg.com/case-studies", "crawler_type": "sitemap", "discovery_url": "https://kpmg.com/case-studies", "sitemap": "", "rss": "", "category": "consulting", "priority": 2, "enabled": True},
    {"org": "Capgemini", "source_name": "Capgemini Case Studies", "base_url": "https://www.capgemini.com/case-studies/", "crawler_type": "sitemap", "discovery_url": "https://www.capgemini.com/case-studies/", "sitemap": "", "rss": "", "category": "consulting", "priority": 2, "enabled": True},

    # ── Research & Analysts ──
    {"org": "Gartner", "source_name": "Gartner Case Studies", "base_url": "https://www.gartner.com/en/case-studies", "crawler_type": "rss", "discovery_url": "https://www.gartner.com/en/case-studies", "sitemap": "", "rss": "", "category": "research", "priority": 1, "enabled": True},
    {"org": "Forrester", "source_name": "Forrester Case Studies", "base_url": "https://www.forrester.com/case-studies", "crawler_type": "rss", "discovery_url": "https://www.forrester.com/case-studies", "sitemap": "", "rss": "", "category": "research", "priority": 2, "enabled": True},
    {"org": "IDC", "source_name": "IDC Case Studies", "base_url": "https://www.idc.com/case-studies", "crawler_type": "rss", "discovery_url": "https://www.idc.com/case-studies", "sitemap": "", "rss": "", "category": "research", "priority": 2, "enabled": True},

    # ── Government Digital ──
    {"org": "USDS", "source_name": "US Digital Service", "base_url": "https://www.usds.gov/", "crawler_type": "sitemap", "discovery_url": "https://www.usds.gov/", "sitemap": "", "rss": "", "category": "government", "priority": 2, "enabled": True},
    {"org": "GSA", "source_name": "GSA Case Studies", "base_url": "https://www.gsa.gov/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.gsa.gov/case-studies", "sitemap": "", "rss": "", "category": "government", "priority": 2, "enabled": True},
    {"org": "NHS", "source_name": "NHS Digital Case Studies", "base_url": "https://digital.nhs.uk/case-studies", "crawler_type": "sitemap", "discovery_url": "https://digital.nhs.uk/case-studies", "sitemap": "", "rss": "", "category": "government", "priority": 2, "enabled": True},
    {"org": "Australia DTA", "source_name": "Australian DTA Case Studies", "base_url": "https://www.dta.gov.au/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.dta.gov.au/case-studies", "sitemap": "", "rss": "", "category": "government", "priority": 3, "enabled": True},
    {"org": "Canada", "source_name": "Government of Canada Digital", "base_url": "https://digital.canada.ca/", "crawler_type": "sitemap", "discovery_url": "https://digital.canada.ca/", "sitemap": "", "rss": "", "category": "government", "priority": 3, "enabled": True},
    {"org": "EU Commission", "source_name": "EU Digital Initiatives", "base_url": "https://digital-strategy.ec.europa.eu/", "crawler_type": "sitemap", "discovery_url": "https://digital-strategy.ec.europa.eu/", "sitemap": "", "rss": "", "category": "government", "priority": 3, "enabled": True},

    # ── Academic (real deployments only) ──
    {"org": "MIT", "source_name": "MIT Sloan Case Studies", "base_url": "https://mitsloan.mit.edu/case-studies", "crawler_type": "sitemap", "discovery_url": "https://mitsloan.mit.edu/case-studies", "sitemap": "", "rss": "", "category": "academic", "priority": 2, "enabled": True},
    {"org": "Stanford", "source_name": "Stanford HAI Case Studies", "base_url": "https://hai.stanford.edu/case-studies", "crawler_type": "sitemap", "discovery_url": "https://hai.stanford.edu/case-studies", "sitemap": "", "rss": "", "category": "academic", "priority": 2, "enabled": True},
    {"org": "Harvard", "source_name": "Harvard Business School Case Studies", "base_url": "https://www.hbs.edu/case-studies", "crawler_type": "sitemap", "discovery_url": "https://www.hbs.edu/case-studies", "sitemap": "", "rss": "", "category": "academic", "priority": 2, "enabled": True},
    {"org": "NVIDIA", "source_name": "NVIDIA Enterprise Stories", "base_url": "https://www.nvidia.com/en-us/case-studies/", "crawler_type": "sitemap", "discovery_url": "https://www.nvidia.com/en-us/case-studies/", "sitemap": "", "rss": "", "category": "cloud", "priority": 2, "enabled": True},
]

def build_registry():
    now = datetime.now(timezone.utc).isoformat()
    registry = {}
    for s in SOURCES:
        sid = str(uuid.uuid5(uuid.NAMESPACE_URL, s["base_url"]))
        registry[sid] = {
            "id": sid,
            "org": s["org"],
            "source_name": s["source_name"],
            "base_url": s["base_url"],
            "crawler_type": s["crawler_type"],
            "discovery_url": s["discovery_url"],
            "sitemap": s["sitemap"],
            "rss": s["rss"],
            "category": s["category"],
            "priority": s["priority"],
            "enabled": s["enabled"],
            "robots_status": "unknown",
            "last_crawl": None,
            "last_successful_fetch": None,
            "case_studies_discovered": 0,
            "tier1_produced": 0,
            "tier2_produced": 0,
            "avg_evidence_quality": None,
            "avg_retrieval_score": None,
            "crawl_frequency_days": 7,
            "created_at": now,
            "updated_at": now,
        }
    return registry

def main():
    registry = build_registry()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"Source registry created: {REGISTRY_PATH}")
    print(f"Sources seeded: {len(registry)}")
    cats = {}
    for s in registry.values():
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    for c, n in sorted(cats.items()):
        print(f"  {c}: {n}")

if __name__ == "__main__":
    main()
