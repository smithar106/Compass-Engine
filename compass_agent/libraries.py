"""Source Library architecture.

The primary unit of evidence collection is no longer a web page — it is a
**Source Library**: one trusted collection of implementation evidence (a cloud
vendor's customer stories, a consulting firm, a government audit office, SEC
filings, an academic stream). Libraries carry their own health metrics, crawl
progress is persisted so nothing is re-crawled, and campaign planning picks the
single highest-value library for the current benchmark gap. General web search
is only a fallback.

Campaign flow per library: discover → crawl → extract → validate → publish →
metrics, then the planner answers "what is the single highest-value evidence
campaign right now?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from compass_agent.store import AgentStore

log = logging.getLogger("compass_agent.libraries")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourceLibrary:
    id: str
    name: str
    category: str = "cloud_vendor"
    entry_urls: list = field(default_factory=list)
    estimated_quality: float = 0.5
    acquisition: dict = field(default_factory=lambda: {"preferred": "static", "fallback": "static"})
    api_urls: list = field(default_factory=list)
    # health metrics (persisted)
    discovered: int = 0
    processed: int = 0
    accepted: int = 0
    rejected: int = 0
    cost_usd: float = 0.0
    acceptance_rate: float = 0.0
    avg_implementation_fields: float = 0.0
    benchmark_contribution: float = 0.0
    last_crawl: Optional[str] = None
    next_crawl: Optional[str] = None
    acquisition_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "entry_urls": self.entry_urls, "estimated_quality": self.estimated_quality,
            "acquisition": self.acquisition, "api_urls": self.api_urls,
            "acquisition_stats": self.acquisition_stats,
            "discovered": self.discovered, "processed": self.processed,
            "accepted": self.accepted, "rejected": self.rejected,
            "remaining": max(0, self.discovered - self.processed),
            "cost_usd": round(self.cost_usd, 6), "acceptance_rate": round(self.acceptance_rate, 3),
            "avg_implementation_fields": round(self.avg_implementation_fields, 2),
            "benchmark_contribution": round(self.benchmark_contribution, 3),
            "last_crawl": self.last_crawl, "next_crawl": self.next_crawl,
        }


# Curated registry of the world's highest-value implementation-evidence sources.
# Category → high, medium, or low estimated quality per implementation evidence.
LIBRARY_REGISTRY: list[dict] = [
    # Cloud vendors (customer story pages: high implementation density; JS-heavy
    # and paginated → FetchFox browser automation preferred)
    {"id": "aws", "name": "AWS Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://aws.amazon.com/solutions/case-studies/", "https://aws.amazon.com/customers/"],
     "estimated_quality": 0.85, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "microsoft", "name": "Microsoft Customer Stories [DEPRECATED — 404s]", "category": "cloud_vendor",
     "entry_urls": ["https://customers.microsoft.com/en-us/"],
     "estimated_quality": 0.15, "acquisition": {"preferred": "static", "fallback": "static"}},
    {"id": "google", "name": "Google Cloud Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://cloud.google.com/customers"],
     "estimated_quality": 0.85, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "salesforce", "name": "Salesforce Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.salesforce.com/customer-stories/"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "servicenow", "name": "ServiceNow Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.servicenow.com/customers.html"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "snowflake", "name": "Snowflake Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.snowflake.com/en/customers/"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "databricks", "name": "Databricks Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.databricks.com/customers"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "sap", "name": "SAP Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.sap.com/about/customer-stories.html"],
     "estimated_quality": 0.75, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "oracle", "name": "Oracle Customer Stories", "category": "cloud_vendor",
     "entry_urls": ["https://www.oracle.com/customers/"],
     "estimated_quality": 0.75, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    # Consulting (deep implementation intelligence)
    {"id": "accenture", "name": "Accenture Case Studies", "category": "consulting",
     "entry_urls": ["https://www.accenture.com/us-en/industries", "https://www.accenture.com/us-en/case-studies-index"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "mckinsey", "name": "McKinsey Insights", "category": "consulting",
     "entry_urls": ["https://www.mckinsey.com/capabilities/operations"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "deloitte", "name": "Deloitte Insights", "category": "consulting",
     "entry_urls": ["https://www2.deloitte.com/us/en/insights.html"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "bcg", "name": "BCG Publications", "category": "consulting",
     "entry_urls": ["https://www.bcg.com/publications"],
     "estimated_quality": 0.8, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    # Government / audit (highest provenance; some sites block headless HTTP)
    {"id": "gao", "name": "US GAO Reports", "category": "government",
     "entry_urls": ["https://www.gao.gov/reports"],
     "estimated_quality": 0.95, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "oecd", "name": "OECD Digital Government", "category": "government",
     "entry_urls": ["https://www.oecd.org/digital/"],
     "estimated_quality": 0.9, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "nao", "name": "UK NAO Reports", "category": "government",
     "entry_urls": ["https://www.nao.org.uk/reports/"],
     "estimated_quality": 0.95, "acquisition": {"preferred": "fetchfox", "fallback": "static"}},
    {"id": "nist", "name": "NIST", "category": "government",
     "entry_urls": ["https://www.nist.gov/artificial-intelligence"],
     "estimated_quality": 0.9, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "usds", "name": "US Digital Service", "category": "government",
     "entry_urls": ["https://www.usds.gov/our-work"],
     "estimated_quality": 0.85, "acquisition": {"preferred": "static", "fallback": "fetchfox"}},
    {"id": "gds", "name": "UK GDS Blog", "category": "government",
     "entry_urls": ["https://gds.blog.gov.uk/feed/"],
     "estimated_quality": 0.85, "acquisition": {"preferred": "rss", "fallback": "static"}},
    # Public companies (financial disclosure provenance)
    {"id": "sec", "name": "SEC Filings", "category": "public_company",
     "entry_urls": ["https://www.sec.gov/cgi-bin/browse-edgar"],
     "estimated_quality": 0.9, "acquisition": {"preferred": "direct_api", "fallback": "static"}},
    # Academic (peer-reviewed)
    {"id": "academic", "name": "Academic Implementation Studies", "category": "academic",
     "entry_urls": ["https://arxiv.org/list/cs.CY/recent"],
     "estimated_quality": 0.7, "acquisition": {"preferred": "static", "fallback": "rss"}},
]


def load_library(entry: dict) -> SourceLibrary:
    return SourceLibrary(
        id=entry["id"], name=entry["name"], category=entry.get("category", ""),
        entry_urls=entry.get("entry_urls", []), estimated_quality=entry.get("estimated_quality", 0.5),
        acquisition=entry.get("acquisition") or {"preferred": "static", "fallback": "static"},
        api_urls=entry.get("api_urls", []),
    )


def ensure_libraries(store: AgentStore) -> None:
    """Register any curated library not yet persisted (idempotent)."""
    existing = {l["id"] for l in store.list_libraries()}
    for entry in LIBRARY_REGISTRY:
        if entry["id"] not in existing:
            store.save_library(load_library(entry).to_dict())


def prioritize_libraries(store: AgentStore, max_libraries: int = 3) -> list[dict]:
    """Rank libraries by expected Decision-Brief value.

    score = estimated_quality × acceptance_rate × benchmark_contribution /
    cost_per_processed, with a freshness boost for libraries not crawled recently.
    Libraries with 0 processed pages use a provisional acceptance rate so they
    can rank high enough to be explored.
    """
    now = datetime.now(timezone.utc)
    scored = []
    for lib in store.list_libraries():
        acceptance = lib["acceptance_rate"] if lib["processed"] > 0 else 0.3
        contribution = lib["benchmark_contribution"] or 0.1
        cost_per = (lib["cost_usd"] / lib["processed"]) if lib["processed"] > 0 else 0.001
        base = lib["estimated_quality"] * acceptance * contribution / max(cost_per, 1e-6)
        # freshness: prefer libraries not crawled in the last 6h
        last = lib.get("last_crawl")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt) < timedelta(hours=6):
                    base *= 0.5  # recently crawled → lower priority
            except ValueError:
                pass
        else:
            base *= 1.5  # never crawled → explore
        scored.append((base, lib))
    scored.sort(key=lambda x: -x[0])
    return [lib for _, lib in scored[:max_libraries]]


def library_score(lib: dict) -> float:
    """Public score helper for dashboards."""
    acceptance = lib["acceptance_rate"] if lib["processed"] > 0 else 0.3
    cost_per = (lib["cost_usd"] / lib["processed"]) if lib["processed"] > 0 else 0.001
    return round(lib["estimated_quality"] * acceptance * (lib["benchmark_contribution"] or 0.1) / max(cost_per, 1e-6), 3)


def _discover_pages(store: AgentStore, library: dict, fetcher, limit: int = 25) -> None:
    """Populate the library's pending pages from its entry URLs (and their
    case-study links) without re-crawling pages already tracked."""
    for entry in library.get("entry_urls", [])[:3]:
        store.claim_library_page(entry, library["id"])
        links = []
        try:
            links = fetcher.fetch_links(entry) if hasattr(fetcher, "fetch_links") else []
        except Exception as exc:
            log.warning("library %s entry link discovery failed for %s: %s", library["id"], entry, exc)
        for link in links[:limit]:
            store.claim_library_page(link["url"], library["id"], link.get("title", ""))


def run_library(store: AgentStore, library: dict, pipeline, campaign, max_pages: int = 5) -> dict:
    """Discover → crawl → extract → validate → publish for one Source Library
    using its chosen acquisition strategy (FetchFox / static / RSS / direct API /
    OpenCLI), falling back to the static crawler when the strategy yields nothing.

    Persists per-page progress so already-processed pages are never re-crawled,
    updates the library's health metrics, and records per-strategy performance so
    the planner learns which acquisition works best for this library.
    """
    from compass_agent.acquisition import (
        StaticAcquisition,
        build_strategy,
        pick_strategy,
        record_acquisition_result,
    )
    from compass_agent.discovery import DiscoveryReport

    fetcher = pipeline.fetcher
    strategy_name = pick_strategy(library, store)
    strategy = build_strategy(strategy_name, fetcher, store)
    candidates = strategy.crawl(library, max_pages)
    # fallback to the static crawler when the chosen strategy yields nothing
    if not candidates and strategy_name != "static":
        strategy = StaticAcquisition(fetcher, store)
        candidates = strategy.crawl(library, max_pages)
        strategy_name = "static"

    report = DiscoveryReport(
        workflow=campaign.workflow if campaign else "library",
        business_function=campaign.business_function if campaign else "operations",
    )
    report.sources_discovered = len(candidates)

    for candidate in candidates:
        if pipeline.budget_gate is not None and not pipeline.budget_gate():
            break
        if isinstance(candidate, dict) and candidate.get("organization_name"):
            # structured item (FetchFox / direct API) → validate + ingest
            pipeline._ingest_payload(
                candidate,
                {"url": candidate.get("url", ""), "title": candidate.get("organization_name", "")},
                campaign,
                report,
            )
            continue
        page = {"url": candidate.get("url", ""), "title": candidate.get("title", "")}
        text = fetcher.fetch(page["url"], page.get("title", ""))
        if len(text.strip()) < 120:
            report.rejected += 1
            continue
        pipeline._extract_and_ingest(text, page, campaign, report)

    # update library health metrics (base on current store state)
    cur = next((l for l in store.list_libraries() if l["id"] == library["id"]), library)
    processed = cur["processed"] + report.sources_discovered
    accepted_total = cur["accepted"] + report.accepted
    rejected_total = cur["rejected"] + report.rejected
    store.update_library(
        library["id"],
        discovered=cur["discovered"] + report.sources_discovered,
        processed=processed,
        accepted=accepted_total,
        rejected=rejected_total,
        cost_usd=cur["cost_usd"] + report.cost_usd,
        acceptance_rate=round(accepted_total / max(processed, 1), 3),
        last_crawl=_now(),
    )
    record_acquisition_result(
        store, library["id"], strategy_name,
        accepted=report.accepted, cost=report.cost_usd, pages=report.sources_discovered,
    )
    return {
        "library": library["id"],
        "strategy": strategy_name,
        "pages_processed": report.sources_discovered,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "cost_usd": round(report.cost_usd, 6),
    }
