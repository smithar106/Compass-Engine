import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORTS_DIR = DATA_DIR / "exports"
REGISTRY_DIR = DATA_DIR / "registry"
CACHE_DIR = DATA_DIR / "cache"
SCREENSHOTS_DIR = RAW_DIR / "screenshots"

for d in [RAW_DIR, PROCESSED_DIR, EXPORTS_DIR, REGISTRY_DIR, CACHE_DIR, SCREENSHOTS_DIR,
          RAW_DIR / "html", RAW_DIR / "pdf", RAW_DIR / "images"]:
    d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("COLLECTOR_DATABASE_URL", f"sqlite:///{DATA_DIR / 'collector_v3.db'}")

DEFAULT_USER_AGENT = "CompassCollector/1.0 (+https://compass.com; research@compass.com)"
DEFAULT_RATE_LIMIT = 1.0
DEFAULT_CONCURRENCY = 2
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
CRAWL_DELAY_BACKOFF = 2.0

INTERVENTION_FAMILIES = [
    "process_redesign", "workflow_simplification", "existing_software_optimization",
    "new_software_implementation", "rules_based_automation", "robotic_process_automation",
    "predictive_ai", "generative_ai", "ai_assisted_work", "autonomous_ai",
    "human_in_the_loop_ai", "staffing_increases", "staffing_reallocation",
    "outsourcing", "managed_services", "training", "governance",
    "organizational_restructuring", "policy_changes", "better_measurement_reporting",
    "no_intervention", "further_investigation", "hybrid_combination"
]

BUSINESS_FUNCTIONS = [
    "sales", "marketing", "customer_support", "finance", "accounting",
    "human_resources", "it", "engineering", "operations", "supply_chain",
    "legal", "compliance", "procurement", "product", "design", "research"
]

INDUSTRIES = [
    "technology", "healthcare", "finance", "manufacturing", "retail",
    "energy", "education", "government", "telecommunications", "transportation",
    "real_estate", "media", "agriculture", "construction", "hospitality"
]

RESULT_STATUSES = ["successful", "partial", "failed", "abandoned", "neutral", "ongoing", "unknown"]

SEARCH_TERMS = {
    "success": ["case study", "results", "outcomes", "ROI", "savings", "improvement"],
    "failure": ["failed", "abandoned", "over budget", "underperformed", "reverted"],
    "neutral": ["pilot", "experiment", "trial", "assessment", "evaluation"]
}

VALUE_TYPES = ["reported", "calculated", "estimated_by_source", "projected_by_source", "normalized", "unknown"]
