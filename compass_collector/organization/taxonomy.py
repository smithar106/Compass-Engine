"""Controlled taxonomies for organization and industry matching.

Phase 2 of the organization/industry upgrade. Defines canonical vocabularies
for industry, subsector, business model, organization size, geography,
regulatory intensity, operational function, and workflow — plus deterministic
normalization that maps the fragmented free-text values in the evidence graph
onto the canonical set while preserving the raw value and provenance.

Design rules:
  * Everything is deterministic — same input, same output.
  * Raw values are preserved; normalized values carry provenance
    (raw, value, source, explicit|inferred, confidence, version).
  * Equivalent labels normalize consistently (e.g. Financial Services,
    Finance, Banking, FinTech, Financial Technology → financial_services).
  * Multi-industry labels ("Insurance / HealthTech") split into parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

NORMALIZATION_VERSION = "org-v1"

# ---------------------------------------------------------------------------
# Canonical industry taxonomy (industry → subsectors)
# ---------------------------------------------------------------------------

# key -> {label, subsectors: {key: label}}
INDUSTRY_TAXONOMY: dict[str, dict] = {
    "financial_services": {
        "label": "Financial Services",
        "subsectors": {
            "banking": "Banking",
            "insurance": "Insurance",
            "capital_markets": "Capital Markets",
            "payments": "Payments",
            "wealth_management": "Wealth Management",
            "lending": "Lending & Credit",
            "fintech": "Financial Technology",
            "general": "Financial Services (general)",
        },
    },
    "healthcare": {
        "label": "Healthcare & Life Sciences",
        "subsectors": {
            "healthcare": "Healthcare",
            "pharmaceuticals": "Pharmaceuticals",
            "biotechnology": "Biotechnology",
            "medical_devices": "Medical Devices",
            "health_insurance": "Health Insurance",
            "life_sciences": "Life Sciences",
            "public_health": "Public Health",
            "general": "Healthcare (general)",
        },
    },
    "technology": {
        "label": "Technology",
        "subsectors": {
            "software": "Software",
            "cloud": "Cloud & Infrastructure",
            "ai": "Artificial Intelligence",
            "hardware": "Hardware & Devices",
            "semiconductors": "Semiconductors",
            "it_services": "IT Services",
            "cybersecurity": "Cybersecurity",
            "enterprise_software": "Enterprise Software",
            "consumer_tech": "Consumer Technology",
            "general": "Technology (general)",
        },
    },
    "manufacturing": {
        "label": "Manufacturing",
        "subsectors": {
            "general": "Manufacturing (general)",
            "automotive": "Automotive",
            "electronics": "Electronics",
            "aerospace_defense": "Aerospace & Defense",
            "food_beverage": "Food & Beverage",
            "industrial": "Industrial",
            "metals": "Metals & Materials",
            "building_products": "Building Products",
            "machinery": "Machinery",
            "semiconductor_manufacturing": "Semiconductor Manufacturing",
        },
    },
    "retail_consumer": {
        "label": "Retail & Consumer",
        "subsectors": {
            "retail": "Retail",
            "ecommerce": "E-commerce",
            "consumer_goods": "Consumer Goods",
            "cpg": "Consumer Packaged Goods",
            "apparel": "Apparel & Fashion",
            "food_service": "Food Service & Restaurants",
            "grocery": "Grocery",
            "luxury": "Luxury Goods",
            "general": "Retail & Consumer (general)",
        },
    },
    "energy_utilities": {
        "label": "Energy & Utilities",
        "subsectors": {
            "oil_gas": "Oil & Gas",
            "utilities": "Utilities",
            "renewable": "Renewable Energy",
            "environmental": "Environmental Services",
            "general": "Energy (general)",
        },
    },
    "government": {
        "label": "Government & Public Sector",
        "subsectors": {
            "government": "Government",
            "public_sector": "Public Sector",
            "defense": "Defense",
            "public_safety": "Public Safety",
            "international": "International & Development",
            "general": "Government (general)",
        },
    },
    "education": {
        "label": "Education",
        "subsectors": {
            "education": "Education",
            "higher_education": "Higher Education",
            "edtech": "EdTech",
            "research": "Research",
            "general": "Education (general)",
        },
    },
    "telecommunications": {
        "label": "Telecommunications",
        "subsectors": {
            "telecom": "Telecommunications",
            "communications": "Communications & ICT",
            "general": "Telecommunications (general)",
        },
    },
    "transportation_logistics": {
        "label": "Transportation & Logistics",
        "subsectors": {
            "transportation": "Transportation",
            "logistics": "Logistics & Distribution",
            "airline": "Aviation & Airlines",
            "freight": "Freight & Trucking",
            "rail": "Rail",
            "automotive": "Automotive (Transport)",
            "general": "Transportation & Logistics (general)",
        },
    },
    "media_entertainment": {
        "label": "Media & Entertainment",
        "subsectors": {
            "media": "Media",
            "entertainment": "Entertainment",
            "gaming": "Gaming & Esports",
            "streaming": "Streaming",
            "advertising": "Advertising",
            "sports": "Sports",
            "publishing": "Publishing",
            "general": "Media & Entertainment (general)",
        },
    },
    "professional_services": {
        "label": "Professional Services",
        "subsectors": {
            "consulting": "Consulting",
            "legal": "Legal",
            "accounting": "Accounting & Tax",
            "hr": "HR & Workforce Services",
            "engineering": "Engineering Services",
            "general": "Professional Services (general)",
        },
    },
    "construction_realestate": {
        "label": "Construction & Real Estate",
        "subsectors": {
            "construction": "Construction",
            "real_estate": "Real Estate",
            "engineering": "Engineering & Construction",
            "general": "Construction & Real Estate (general)",
        },
    },
    "agriculture": {
        "label": "Agriculture & Food",
        "subsectors": {
            "agriculture": "Agriculture",
            "agribusiness": "Agribusiness",
            "food": "Food & Beverage",
            "dairy": "Dairy",
            "general": "Agriculture & Food (general)",
        },
    },
    "hospitality": {
        "label": "Hospitality & Travel",
        "subsectors": {
            "hospitality": "Hospitality",
            "travel": "Travel",
            "food_service": "Food Service & Restaurants",
            "casino": "Gaming & Casinos",
            "general": "Hospitality (general)",
        },
    },
    "nonprofit": {
        "label": "Nonprofit & NGO",
        "subsectors": {
            "nonprofit": "Nonprofit",
            "international_development": "International Development",
            "philanthropy": "Philanthropy",
            "general": "Nonprofit (general)",
        },
    },
    "pharmaceuticals": {
        "label": "Pharmaceuticals & Life Sciences",
        "subsectors": {
            "pharmaceuticals": "Pharmaceuticals",
            "life_sciences": "Life Sciences",
            "general": "Pharmaceuticals (general)",
        },
    },
}

# Canonical industry keys
CANONICAL_INDUSTRIES = {k: v["label"] for k, v in INDUSTRY_TAXONOMY.items()}

# ---------------------------------------------------------------------------
# Alias map: normalized phrase → (industry_key, subsector_key, confidence)
# ---------------------------------------------------------------------------

_SUBSECTOR_KEYWORDS: dict[str, dict[str, str]] = {
    "financial_services": {
        "bank": "banking",
        "banking": "banking",
        "insurance": "insurance",
        "capital market": "capital_markets",
        "payment": "payments",
        "wealth": "wealth_management",
        "fintech": "fintech",
        "financial technology": "fintech",
        "lend": "lending",
        "financ": "general",
    },
    "healthcare": {
        "pharm": "pharmaceuticals",
        "biotech": "biotechnology",
        "medical device": "medical_devices",
        "life science": "life_sciences",
        "health insur": "health_insurance",
        "public health": "public_health",
        "veterinary": "healthcare",
        "pet care": "healthcare",
        "nutraceutical": "life_sciences",
        "health": "healthcare",
    },
    "technology": {
        "software": "software",
        "saas": "software",
        "cloud": "cloud",
        "data center": "cloud",
        "infrastructure": "cloud",
        "it infrastructure": "cloud",
        "artificial intelligence": "ai",
        "machine learning": "ai",
        "generative ai": "ai",
        "ai": "ai",
        "semiconductor": "semiconductors",
        "hardware": "hardware",
        "security": "cybersecurity",
        "cyber": "cybersecurity",
        "it service": "it_services",
        "information management": "it_services",
        "technology": "general",
        "computer": "general",
    },
    "manufacturing": {
        "automotive": "automotive",
        "electron": "electronics",
        "aerospace": "aerospace_defense",
        "defense": "aerospace_defense",
        "metal": "metals",
        "building": "building_products",
        "machiner": "machinery",
        "manufactur": "general",
        "semiconductor": "semiconductor_manufacturing",
        "industrial": "industrial",
        "automation": "industrial",
        "pulp": "industrial",
        "paper": "industrial",
        "floor care": "industrial",
        "marine": "industrial",
        "appliance": "industrial",
        "conglomerate": "general",
    },
    "retail_consumer": {
        "e-commerce": "ecommerce",
        "ecommerce": "ecommerce",
        "consumer packaged": "cpg",
        "consumer goods": "consumer_goods",
        "apparel": "apparel",
        "fashion": "apparel",
        "footwear": "apparel",
        "restaurant": "food_service",
        "food service": "food_service",
        "fast food": "food_service",
        "grocery": "grocery",
        "luxury": "luxury",
        "retail": "retail",
        "consumer": "consumer_goods",
    },
    "energy_utilities": {
        "oil": "oil_gas",
        "gas": "oil_gas",
        "tank storage": "oil_gas",
        "biofuel": "oil_gas",
        "utilit": "utilities",
        "solar": "renewable",
        "renewable": "renewable",
        "energy": "general",
        "environmental": "environmental",
        "waste": "environmental",
    },
    "government": {
        "government": "government",
        "public sector": "public_sector",
        "public": "public_sector",
        "defen": "defense",
        "police": "public_safety",
        "law enforcement": "public_safety",
        "international development": "international",
    },
    "education": {
        "education": "education",
        "university": "higher_education",
        "higher education": "higher_education",
        "edtech": "edtech",
        "school": "education",
        "research": "research",
    },
    "telecommunications": {
        "telecom": "telecom",
        "ict": "communications",
        "communications": "communications",
        "connectivity": "telecom",
    },
    "transportation_logistics": {
        "logistic": "logistics",
        "distribution": "logistics",
        "delivery": "logistics",
        "freight": "freight",
        "trucking": "freight",
        "airline": "airline",
        "aviation": "airline",
        "rail": "rail",
        "transport": "transportation",
        "mobility": "transportation",
        "automotive": "automotive",
        "shipping": "freight",
    },
    "media_entertainment": {
        "media": "media",
        "entertainment": "entertainment",
        "gaming": "gaming",
        "sport": "sports",
        "streaming": "streaming",
        "advertis": "advertising",
        "publish": "publishing",
        "broadcast": "media",
    },
    "professional_services": {
        "consult": "consulting",
        "legal": "legal",
        "law": "legal",
        "account": "accounting",
        "tax": "accounting",
        "hr": "hr",
        "human resource": "hr",
        "staffing": "hr",
        "workforce": "hr",
        "fleet management": "hr",
        "engineering service": "engineering",
        "professional service": "general",
        "service": "general",
        "business process outsourcing": "general",
        "risk management": "general",
    },
    "construction_realestate": {
        "construction": "construction",
        "real estate": "real_estate",
        "building product": "construction",
        "engineering": "engineering",
        "architecture": "engineering",
    },
    "agriculture": {
        "agriculture": "agriculture",
        "agribusiness": "agribusiness",
        "food": "food",
        "dairy": "dairy",
        "beverage": "food",
    },
    "hospitality": {
        "hospitality": "hospitality",
        "hotel": "hospitality",
        "travel": "travel",
        "tourism": "travel",
        "casino": "casino",
        "restaurant": "food_service",
    },
    "nonprofit": {
        "nonprofit": "nonprofit",
        "non-profit": "nonprofit",
        "ngo": "nonprofit",
        "international development": "international_development",
        "charity": "nonprofit",
    },
    "pharmaceuticals": {
        "pharm": "pharmaceuticals",
        "life science": "life_sciences",
        "biotech": "pharmaceuticals",
    },
}

# Exact alias phrases (normalized) → (industry_key, subsector_key)
# Covers the highest-frequency raw values observed in the audit, including the
# Finance cluster fragmentation.
_ALIASES: dict[str, tuple[str, str]] = {
    "financial services": ("financial_services", "general"),
    "financial_services": ("financial_services", "general"),
    "finance": ("financial_services", "general"),
    "financing": ("financial_services", "general"),
    "banking": ("financial_services", "banking"),
    "bank": ("financial_services", "banking"),
    "retail banking": ("financial_services", "banking"),
    "digital banking": ("financial_services", "banking"),
    "banking and financial services": ("financial_services", "banking"),
    "banking financial services": ("financial_services", "banking"),
    "banking and financial": ("financial_services", "banking"),
    "insurance": ("financial_services", "insurance"),
    "insurance and financial services": ("financial_services", "insurance"),
    "health insurance": ("healthcare", "health_insurance"),
    "capital markets": ("financial_services", "capital_markets"),
    "wealth management": ("financial_services", "wealth_management"),
    "payments": ("financial_services", "payments"),
    "payment processing": ("financial_services", "payments"),
    "fintech": ("financial_services", "fintech"),
    "financial technology": ("financial_services", "fintech"),
    "lending": ("financial_services", "lending"),
    "financial services and banking": ("financial_services", "banking"),
    # Technology
    "technology": ("technology", "general"),
    "software": ("technology", "software"),
    "saas": ("technology", "software"),
    "cloud computing": ("technology", "cloud"),
    "cloud services": ("technology", "cloud"),
    "cloud": ("technology", "cloud"),
    "artificial intelligence": ("technology", "ai"),
    "ai": ("technology", "ai"),
    "machine learning": ("technology", "ai"),
    "semiconductors": ("technology", "semiconductors"),
    "semiconductor": ("technology", "semiconductors"),
    "cybersecurity": ("technology", "cybersecurity"),
    "security": ("technology", "cybersecurity"),
    "enterprise software": ("technology", "enterprise_software"),
    "it services": ("technology", "it_services"),
    "technology services": ("technology", "it_services"),
    "information technology": ("technology", "it_services"),
    "high-tech": ("technology", "general"),
    "electronics": ("manufacturing", "electronics"),
    "hardware": ("technology", "hardware"),
    # Healthcare
    "healthcare": ("healthcare", "healthcare"),
    "health care": ("healthcare", "healthcare"),
    "healthcare and life sciences": ("healthcare", "life_sciences"),
    "life sciences": ("healthcare", "life_sciences"),
    "pharmaceuticals": ("healthcare", "pharmaceuticals"),
    "pharmaceutical": ("healthcare", "pharmaceuticals"),
    "biotechnology": ("healthcare", "biotechnology"),
    "biotech": ("healthcare", "biotechnology"),
    "medical devices": ("healthcare", "medical_devices"),
    "medical technology": ("healthcare", "medical_devices"),
    "medtech": ("healthcare", "medical_devices"),
    "health tech": ("healthcare", "healthcare"),
    "healthcare technology": ("healthcare", "healthcare"),
    # Manufacturing
    "manufacturing": ("manufacturing", "general"),
    "industrial": ("manufacturing", "industrial"),
    "industrial automation": ("manufacturing", "industrial"),
    "automotive": ("manufacturing", "automotive"),
    "aerospace and defense": ("manufacturing", "aerospace_defense"),
    "aerospace": ("manufacturing", "aerospace_defense"),
    "defense": ("government", "defense"),
    "machinery": ("manufacturing", "machinery"),
    "steel production and marketing": ("manufacturing", "metals"),
    "steel": ("manufacturing", "metals"),
    "metals": ("manufacturing", "metals"),
    "chemicals": ("manufacturing", "industrial"),
    "packaging": ("manufacturing", "industrial"),
    "building products": ("manufacturing", "building_products"),
    "building materials": ("manufacturing", "building_products"),
    # Retail & Consumer
    "retail": ("retail_consumer", "retail"),
    "consumer goods": ("retail_consumer", "consumer_goods"),
    "consumer products": ("retail_consumer", "consumer_goods"),
    "consumer packaged goods": ("retail_consumer", "cpg"),
    "cpg": ("retail_consumer", "cpg"),
    "e-commerce": ("retail_consumer", "ecommerce"),
    "ecommerce": ("retail_consumer", "ecommerce"),
    "apparel": ("retail_consumer", "apparel"),
    "fashion": ("retail_consumer", "apparel"),
    "footwear": ("retail_consumer", "apparel"),
    "luxury goods": ("retail_consumer", "luxury"),
    "restaurants": ("retail_consumer", "food_service"),
    "restaurant": ("retail_consumer", "food_service"),
    "food service": ("retail_consumer", "food_service"),
    "fast food": ("retail_consumer", "food_service"),
    "grocery": ("retail_consumer", "grocery"),
    "grocery retail": ("retail_consumer", "grocery"),
    "food and beverage": ("agriculture", "food"),
    "food & beverage": ("agriculture", "food"),
    "food": ("agriculture", "food"),
    "beverage": ("agriculture", "food"),
    "food and beverage and agriculture": ("agriculture", "food"),
    # Energy
    "energy": ("energy_utilities", "general"),
    "energy and utilities": ("energy_utilities", "utilities"),
    "oil and gas": ("energy_utilities", "oil_gas"),
    "oil & gas": ("energy_utilities", "oil_gas"),
    "utilities": ("energy_utilities", "utilities"),
    "solar energy": ("energy_utilities", "renewable"),
    "power management": ("energy_utilities", "utilities"),
    "environmental services": ("energy_utilities", "environmental"),
    "waste management": ("energy_utilities", "environmental"),
    "environmental and hazardous waste management services": ("energy_utilities", "environmental"),
    # Government
    "government": ("government", "government"),
    "public sector": ("government", "public_sector"),
    "government public sector": ("government", "public_sector"),
    "government and public sector": ("government", "public_sector"),
    "public sector government": ("government", "public_sector"),
    "government and defense": ("government", "defense"),
    "government defense": ("government", "defense"),
    "government defence": ("government", "defense"),
    "public administration": ("government", "public_sector"),
    "public governance": ("government", "public_sector"),
    "global public sector": ("government", "public_sector"),
    "public safety law enforcement": ("government", "public_safety"),
    "policing": ("government", "public_safety"),
    # Education
    "education": ("education", "education"),
    "higher education": ("education", "higher_education"),
    "edtech": ("education", "edtech"),
    "education technology": ("education", "edtech"),
    "university": ("education", "higher_education"),
    "academic research": ("education", "research"),
    # Telecom
    "telecommunications": ("telecommunications", "telecom"),
    "communications and it": ("telecommunications", "communications"),
    "ict": ("telecommunications", "communications"),
    "unified communications as a service": ("telecommunications", "communications"),
    "contact center as a service": ("telecommunications", "communications"),
    # Transport & Logistics
    "transportation": ("transportation_logistics", "transportation"),
    "logistics": ("transportation_logistics", "logistics"),
    "distribution": ("transportation_logistics", "logistics"),
    "supply chain": ("transportation_logistics", "logistics"),
    "logistics supply chain": ("transportation_logistics", "logistics"),
    "supply chain management": ("transportation_logistics", "logistics"),
    "airline": ("transportation_logistics", "airline"),
    "airlines": ("transportation_logistics", "airline"),
    "aviation": ("transportation_logistics", "airline"),
    "freight transportation": ("transportation_logistics", "freight"),
    "trucking and transport services": ("transportation_logistics", "freight"),
    "railroad": ("transportation_logistics", "rail"),
    "mobility": ("transportation_logistics", "transportation"),
    "car sharing": ("transportation_logistics", "transportation"),
    # Media
    "media": ("media_entertainment", "media"),
    "media and entertainment": ("media_entertainment", "entertainment"),
    "media and communications": ("media_entertainment", "media"),
    "entertainment": ("media_entertainment", "entertainment"),
    "gaming": ("media_entertainment", "gaming"),
    "gaming and esports": ("media_entertainment", "gaming"),
    "streaming": ("media_entertainment", "streaming"),
    "video streaming": ("media_entertainment", "streaming"),
    "advertising": ("media_entertainment", "advertising"),
    "outdoor advertising": ("media_entertainment", "advertising"),
    "digital marketing": ("media_entertainment", "advertising"),
    "marketing": ("media_entertainment", "advertising"),
    "publishing": ("media_entertainment", "publishing"),
    "social media": ("media_entertainment", "media"),
    "sports": ("media_entertainment", "sports"),
    "sports technology": ("media_entertainment", "sports"),
    "sports and entertainment": ("media_entertainment", "sports"),
    "gambling": ("media_entertainment", "gaming"),
    # Professional services
    "professional services": ("professional_services", "general"),
    "consulting": ("professional_services", "consulting"),
    "consulting and engineering": ("professional_services", "consulting"),
    "legal services": ("professional_services", "legal"),
    "legal": ("professional_services", "legal"),
    "accounting": ("professional_services", "accounting"),
    "human resources": ("professional_services", "hr"),
    "hr services": ("professional_services", "hr"),
    "recruitment": ("professional_services", "hr"),
    "staffing": ("professional_services", "hr"),
    "engineering services": ("professional_services", "engineering"),
    "engineering": ("professional_services", "engineering"),
    "information services": ("technology", "it_services"),
    # Construction / Real estate
    "construction": ("construction_realestate", "construction"),
    "construction and engineering": ("construction_realestate", "engineering"),
    "real estate": ("construction_realestate", "real_estate"),
    # Agriculture
    "agriculture": ("agriculture", "agriculture"),
    "agribusiness": ("agriculture", "agribusiness"),
    "dairy": ("agriculture", "dairy"),
    "food and beverage": ("agriculture", "food"),
    # Hospitality / Travel
    "hospitality": ("hospitality", "hospitality"),
    "travel": ("hospitality", "travel"),
    "travel and hospitality": ("hospitality", "travel"),
    "hotels": ("hospitality", "hospitality"),
    # Nonprofit
    "nonprofit": ("nonprofit", "nonprofit"),
    "non-profit": ("nonprofit", "nonprofit"),
    "non profit": ("nonprofit", "nonprofit"),
    "international development": ("nonprofit", "international_development"),
    "n a cross industry academic research": ("nonprofit", "nonprofit"),
    # Miscellaneous
    "pest control": ("professional_services", "general"),
    "printing": ("manufacturing", "industrial"),
    "mining": ("energy_utilities", "general"),
    "construction materials distribution": ("construction_realestate", "construction"),
    "electrical and automation distribution": ("manufacturing", "industrial"),
    "industrial distribution": ("manufacturing", "industrial"),
    "building automation": ("manufacturing", "building_products"),
    "smart buildings": ("manufacturing", "building_products"),
    "smart home services": ("technology", "hardware"),
}

# Geography taxonomy
GEOGRAPHY_ALIASES: dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "u.s": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "gb": "United Kingdom",
    "great britain": "United Kingdom",
    "germany": "Germany",
    "de": "Germany",
    "france": "France",
    "canada": "Canada",
    "ca": "Canada",
    "japan": "Japan",
    "jp": "Japan",
    "australia": "Australia",
    "au": "Australia",
    "india": "India",
    "china": "China",
    "singapore": "Singapore",
    "brazil": "Brazil",
    "netherlands": "Netherlands",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "spain": "Spain",
    "italy": "Italy",
    "europe": "Europe",
    "eu": "Europe",
    "european union": "Europe",
    "middle east": "Middle East",
    "north america": "North America",
    "latin america": "Latin America",
    "asia pacific": "Asia Pacific",
    "apac": "Asia Pacific",
    "africa": "Africa",
    "global": "Global",
    "worldwide": "Global",
    "international": "Global",
}

# Business model taxonomy
BUSINESS_MODELS: dict[str, str] = {
    "b2b_saas": "B2B SaaS",
    "b2c": "B2C",
    "b2b": "B2B",
    "marketplace": "Marketplace",
    "d2c": "D2C",
    "enterprise_software": "Enterprise Software",
    "manufacturer": "Manufacturer",
    "distributor": "Distributor",
    "services": "Services",
    "consulting": "Consulting",
    "government": "Government",
    "nonprofit": "Nonprofit",
    "financial_institution": "Financial Institution",
    "utility": "Utility",
    "conglomerate": "Conglomerate",
}

# Regulatory intensity taxonomy
REGULATORY_LEVELS: list[str] = ["low", "medium", "high", "critical"]

REGULATORY_BY_INDUSTRY: dict[str, str] = {
    "financial_services": "critical",
    "healthcare": "high",
    "government": "high",
    "energy_utilities": "high",
    "transportation_logistics": "medium",
    "pharmaceuticals": "critical",
    "telecommunications": "medium",
    "education": "low",
    "technology": "low",
    "manufacturing": "medium",
    "retail_consumer": "low",
    "media_entertainment": "low",
    "professional_services": "medium",
    "construction_realestate": "medium",
    "agriculture": "medium",
    "hospitality": "low",
    "nonprofit": "low",
}

# Employee size bands
EMPLOYEE_BANDS: list[str] = ["<10", "10-50", "50-200", "200-1000", "1000-10000", "10000+"]
EMPLOYEE_BAND_MAP: dict[tuple[int, int], str] = {
    (0, 10): "<10",
    (10, 50): "10-50",
    (50, 200): "50-200",
    (200, 1000): "200-1000",
    (1000, 10000): "1000-10000",
    (10000, None): "10000+",
}

REVENUE_BANDS: list[str] = ["<1M", "1M-10M", "10M-100M", "100M-1B", "1B-10B", "10B+"]

# Operational functions (reuse engine's business functions + aliases)
OPERATIONAL_FUNCTIONS: list[str] = [
    "sales", "marketing", "customer_support", "finance", "accounting",
    "human_resources", "it", "engineering", "operations", "supply_chain",
    "legal", "compliance", "procurement", "product", "design", "research",
]

# Workflows (reuse the engine's workflow taxonomy)
from compass_collector.analysis.comparability import ALL_WORKFLOWS  # noqa: E402

WORKFLOWS: list[str] = ALL_WORKFLOWS


# ---------------------------------------------------------------------------
# Normalized field value with provenance
# ---------------------------------------------------------------------------

@dataclass
class NormalizedValue:
    raw: str
    value: str
    source: str = "taxonomy"
    method: str = "explicit"  # explicit | inferred
    confidence: float = 1.0
    version: str = NORMALIZATION_VERSION

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "value": self.value,
            "source": self.source,
            "method": self.method,
            "confidence": round(self.confidence, 3),
            "version": self.version,
        }


@dataclass
class IndustryNormalization:
    raw: str
    canonical: Optional[str] = None      # industry key
    broader: Optional[str] = None        # industry group label
    subsector: Optional[str] = None      # subsector key
    parts: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    mapped: bool = False

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "canonical": self.canonical,
            "broader": self.broader,
            "subsector": self.subsector,
            "parts": self.parts,
            "confidence": round(self.confidence, 3),
            "mapped": self.mapped,
            "version": NORMALIZATION_VERSION,
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]*\)")
_FILLER_RE = re.compile(r"\b(the|and|&|inc|inc\.|corp|corp\.|co|company|llc|ltd)\b\.?")


def _clean(raw: str) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().lower()
    text = _PAREN_RE.sub("", text)           # drop parenthetical annotations
    text = text.replace("_", " ").replace("-", " ").replace("/", " / ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" / ", "/")           # normalize slashes after spacing
    return text


def _alias_key(raw: str) -> str:
    """Fully-normalized lookup key for the alias map (dashes/underscores→space)."""
    return re.sub(r"\s+", " ", str(raw).strip().lower().replace("_", " ").replace("-", " "))


# Alias map keyed by cleaned form so lookups are consistent with _clean.
_ALIAS_LOOKUP: dict[str, tuple[str, str]] = {
    _alias_key(k): v for k, v in _ALIASES.items()
}


def _split_parts(cleaned: str) -> list[str]:
    if "/" in cleaned:
        return [p.strip() for p in cleaned.split("/") if p.strip()]
    if " & " in cleaned or " and " in cleaned:
        # keep as a single phrase; the alias map handles "food and beverage"
        return [cleaned]
    return [cleaned]


def _exact_alias(part: str) -> Optional[tuple[str, str]]:
    return _ALIAS_LOOKUP.get(_alias_key(part))


def _keyword_match(part: str) -> Optional[tuple[str, str, float]]:
    for industry_key, keywords in _SUBSECTOR_KEYWORDS.items():
        for kw, subsector in keywords.items():
            if kw in part:
                return industry_key, subsector, 0.7
    return None


def normalize_industry(raw: str) -> IndustryNormalization:
    """Normalize a single (possibly compound) industry label."""
    cleaned = _clean(raw)
    if not cleaned:
        return IndustryNormalization(raw=raw or "")

    parts = _split_parts(cleaned)
    matched: list[dict] = []
    total_conf = 0.0

    for part in parts:
        exact = _exact_alias(part)
        if exact:
            ind_key, sub_key = exact
            entry = {
                "raw_part": part,
                "industry": ind_key,
                "subsector": sub_key,
                "confidence": 1.0,
                "method": "explicit",
            }
            matched.append(entry)
            total_conf += 1.0
            continue
        kw = _keyword_match(part)
        if kw:
            ind_key, sub_key, conf = kw
            entry = {
                "raw_part": part,
                "industry": ind_key,
                "subsector": sub_key,
                "confidence": conf,
                "method": "inferred",
            }
            matched.append(entry)
            total_conf += conf
            continue
        matched.append(
            {
                "raw_part": part,
                "industry": None,
                "subsector": None,
                "confidence": 0.0,
                "method": "inferred",
            }
        )

    if matched and any(m.get("industry") for m in matched):
        # Primary = highest-confidence matched part (compound labels may have an
        # unmapped first element, e.g. "Tank Storage / Energy / Chemicals").
        primary = max(matched, key=lambda m: m["confidence"])
        ind_key = primary["industry"]
        subsector = primary.get("subsector")
        return IndustryNormalization(
            raw=raw or "",
            canonical=ind_key,
            broader=CANONICAL_INDUSTRIES.get(ind_key),
            subsector=subsector,
            parts=matched,
            confidence=round(total_conf / len(matched), 3),
            mapped=True,
        )
    return IndustryNormalization(
        raw=raw or "",
        parts=matched,
        confidence=0.0,
        mapped=False,
    )


def normalize_geography(raw: str) -> NormalizedValue:
    if not raw:
        return NormalizedValue(raw="", value="", confidence=0.0)
    key = _clean(raw)
    canonical = GEOGRAPHY_ALIASES.get(key)
    if canonical:
        return NormalizedValue(raw=raw, value=canonical, confidence=1.0)
    return NormalizedValue(raw=raw, value=str(raw).strip(), confidence=0.3, method="inferred")


def employee_count_to_band(count: Optional[int]) -> Optional[str]:
    if count is None or count < 0:
        return None
    for (lo, hi), band in EMPLOYEE_BAND_MAP.items():
        if hi is None:
            if count >= lo:
                return band
        elif lo <= count < hi:
            return band
    return None


def normalize_employee_count(raw) -> NormalizedValue:
    if raw is None:
        return NormalizedValue(raw="", value="", confidence=0.0)
    try:
        count = int(float(raw))
    except (TypeError, ValueError):
        return NormalizedValue(raw=str(raw), value="", confidence=0.0, method="inferred")
    band = employee_count_to_band(count)
    return NormalizedValue(
        raw=str(raw),
        value=str(count),
        confidence=1.0,
        source="employee_count",
    )


def normalize_operational_function(raw) -> NormalizedValue:
    if not raw:
        return NormalizedValue(raw="", value="", confidence=0.0)
    text = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    # Multi-label values ("customer_support, marketing, operations",
    # "Ancillary Revenue / Guest Services") reduce to their first element.
    if "," in text or "/" in text:
        text = text.split(",")[0].split("/")[0].strip("_ ")
    key = text
    if key in OPERATIONAL_FUNCTIONS:
        return NormalizedValue(raw=raw, value=key, confidence=1.0)
    aliases = {
        "hr": "human_resources",
        "support": "customer_support",
        "customer_service": "customer_support",
        "customer_support": "customer_support",
        "supply_chain_management": "supply_chain",
        "supply_chain_&_logistics": "supply_chain",
        "logistics": "supply_chain",
        "data_&_analytics": "operations",
        "analytics": "operations",
        "risk_management_/_fraud_prevention": "compliance",
        "risk_management": "compliance",
        "ancillary_revenue": "operations",
        "guest_services": "operations",
        "project_management": "operations",
        "human_resources_/_recruiting": "human_resources",
        "recruiting": "human_resources",
    }
    if key in aliases:
        return NormalizedValue(raw=raw, value=aliases[key], confidence=0.9)
    return NormalizedValue(raw=raw, value=key, confidence=0.5, method="inferred")


def regulatory_intensity_for(industry_key: Optional[str]) -> Optional[str]:
    if not industry_key:
        return None
    return REGULATORY_BY_INDUSTRY.get(industry_key)
