"""Known-organization registry.

A curated seed registry of well-known organizations with canonical names,
aliases, domains, and industry/subsector. This is the first resolution tier
(Phase 4). A ``build_registry_from_evidence`` helper can augment it from the
evidence graph at runtime.
"""

from __future__ import annotations

from typing import Optional

# name (lowercased canonical) -> profile stub
CURATED_REGISTRY: dict[str, dict] = {
    "shopify": {
        "canonical_name": "Shopify",
        "aliases": ["shopify", "shopify inc", "shopify inc."],
        "domains": ["shopify.com", "shopify.ca"],
        "industry": "technology",
        "subsector": "ecommerce",
        "business_model": "b2b_saas",
        "headquarters_country": "Canada",
        "operating_geographies": ["Global"],
    },
    "adobe": {
        "canonical_name": "Adobe",
        "aliases": ["adobe", "adobe inc", "adobe systems", "adobe inc."],
        "domains": ["adobe.com"],
        "industry": "technology",
        "subsector": "software",
        "business_model": "b2b_saas",
        "headquarters_country": "United States",
    },
    "amazon": {
        "canonical_name": "Amazon",
        "aliases": ["amazon", "amazon.com", "amazon web services", "aws"],
        "domains": ["amazon.com", "aws.amazon.com"],
        "industry": "retail_consumer",
        "subsector": "ecommerce",
        "business_model": "b2c",
        "headquarters_country": "United States",
    },
    "google": {
        "canonical_name": "Google",
        "aliases": ["google", "google cloud", "alphabet"],
        "domains": ["google.com"],
        "industry": "technology",
        "subsector": "software",
        "business_model": "b2b_saas",
        "headquarters_country": "United States",
    },
    "accenture": {
        "canonical_name": "Accenture",
        "aliases": ["accenture", "accenture plc", "accenture llc"],
        "domains": ["accenture.com"],
        "industry": "professional_services",
        "subsector": "consulting",
        "business_model": "services",
        "headquarters_country": "Ireland",
        "operating_geographies": ["Global"],
    },
    "mckinsey": {
        "canonical_name": "McKinsey & Company",
        "aliases": ["mckinsey", "mckinsey & company", "mckinsey & co"],
        "domains": ["mckinsey.com"],
        "industry": "professional_services",
        "subsector": "consulting",
        "business_model": "consulting",
    },
    "hsbc": {
        "canonical_name": "HSBC",
        "aliases": ["hsbc", "hsbc holdings", "hsbc group"],
        "domains": ["hsbc.com"],
        "industry": "financial_services",
        "subsector": "banking",
        "business_model": "financial_institution",
        "regulatory_context": "critical",
    },
    "jpmorgan": {
        "canonical_name": "JPMorgan Chase",
        "aliases": ["jpmorgan", "jp morgan", "jpmorgan chase", "jpmorgan chase & co", "chase"],
        "domains": ["jpmorganchase.com"],
        "industry": "financial_services",
        "subsector": "banking",
        "business_model": "financial_institution",
        "regulatory_context": "critical",
    },
    "stripe": {
        "canonical_name": "Stripe",
        "aliases": ["stripe", "stripe inc"],
        "domains": ["stripe.com"],
        "industry": "financial_services",
        "subsector": "payments",
        "business_model": "b2b_saas",
        "regulatory_context": "critical",
    },
    "state_street": {
        "canonical_name": "State Street Corporation",
        "aliases": ["state street", "state street corporation", "state street bank"],
        "domains": ["statestreet.com"],
        "industry": "financial_services",
        "subsector": "capital_markets",
        "business_model": "financial_institution",
        "regulatory_context": "critical",
    },
    "pfizer": {
        "canonical_name": "Pfizer",
        "aliases": ["pfizer", "pfizer inc"],
        "domains": ["pfizer.com"],
        "industry": "healthcare",
        "subsector": "pharmaceuticals",
        "business_model": "manufacturer",
        "regulatory_context": "critical",
    },
    "johnson_&_johnson": {
        "canonical_name": "Johnson & Johnson",
        "aliases": ["johnson & johnson", "j&j", "johnson and johnson"],
        "domains": ["jnj.com"],
        "industry": "healthcare",
        "subsector": "pharmaceuticals",
        "business_model": "manufacturer",
        "regulatory_context": "critical",
    },
    "walmart": {
        "canonical_name": "Walmart",
        "aliases": ["walmart", "wal mart", "walmart inc"],
        "domains": ["walmart.com"],
        "industry": "retail_consumer",
        "subsector": "retail",
        "business_model": "b2c",
        "headquarters_country": "United States",
    },
    "bp": {
        "canonical_name": "BP",
        "aliases": ["bp", "bp plc", "british petroleum"],
        "domains": ["bp.com"],
        "industry": "energy_utilities",
        "subsector": "oil_gas",
        "business_model": "utility",
        "regulatory_context": "high",
    },
    "bayer": {
        "canonical_name": "Bayer",
        "aliases": ["bayer", "bayer ag", "bayer healthcare"],
        "domains": ["bayer.com"],
        "industry": "healthcare",
        "subsector": "pharmaceuticals",
        "business_model": "manufacturer",
        "regulatory_context": "critical",
    },
}


def _norm(name: str) -> str:
    """Alphanumeric-only lowercase key for robust name matching."""
    import re

    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def lookup_by_name(name: str) -> Optional[dict]:
    """Exact/alias lookup against the curated registry."""
    if not name:
        return None
    key = _norm(name)
    for entry in CURATED_REGISTRY.values():
        candidates = [entry["canonical_name"], *entry.get("aliases", [])]
        for cand in candidates:
            if key and key == _norm(cand):
                return entry
            # tolerate trailing legal-suffix variants ("Shopify Inc" vs "Shopify")
            norm_cand = _norm(cand)
            if key and norm_cand and (norm_cand.startswith(key) or key.startswith(norm_cand)):
                if len(key) >= 4 or len(norm_cand) >= 4:
                    return entry
    return None


def lookup_by_domain(domain: str) -> Optional[dict]:
    if not domain:
        return None
    dom = str(domain).strip().lower().lstrip("www.").rstrip("/")
    for entry in CURATED_REGISTRY.values():
        for d in entry.get("domains", []):
            if dom == d or dom.endswith("." + d) or d.endswith(dom):
                return entry
    return None


def build_registry_from_evidence(session, name_field="organization_name") -> dict:
    """Augment the curated registry from the evidence graph (runtime use).

    Returns {name_key: {canonical_name, aliases, domains, industry, ...}} built
    from intervention records grouped by canonical organization name.
    """
    from compass_collector.models.intervention import InterventionRecord

    registry: dict[str, dict] = {}
    rows = (
        session.query(
            InterventionRecord.organization_name,
            InterventionRecord.organization_industry,
            InterventionRecord.organization_type,
        )
        .filter(InterventionRecord.organization_name.isnot(None))
        .all()
    )
    for name, industries, org_type in rows:
        key = str(name).strip().lower()
        if not key or key in ("unknown", "n/a", "anonymous"):
            continue
        entry = registry.setdefault(
            key,
            {
                "canonical_name": str(name).strip(),
                "aliases": [],
                "domains": [],
                "industry": None,
                "subsector": None,
                "business_model": None,
            },
        )
        if industries:
            inds = industries if isinstance(industries, list) else [industries]
            for ind in inds:
                if ind:
                    entry.setdefault("_raw_industries", set()).add(str(ind))
    return registry
