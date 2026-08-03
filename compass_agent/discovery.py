"""Discover → Collect → Extract → Validate → Publish pipeline (Discovery Mode).

Reuses the existing Compass collection framework (search query generator,
DuckDuckGo scraper, curated evidence seeds, crawl/fetch) rather than building a
second crawler. Every candidate moves through:

    plan → claim → fetch → parse → extract (LLM, budget-gated) → validate → ingest

Ingestion goes through the engine's `POST /api/evidence/ingest`, which applies
duplicate detection and the quality gate. Campaign counters (discovered /
accepted / rejected / cost) are updated after each candidate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from compass_agent.campaign import Campaign

log = logging.getLogger("compass_agent.discovery")


# ── Search backends ──────────────────────────────────────────────────────

class SearchBackend:
    """Protocol: given a query, return [{url, title, snippet}]."""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        raise NotImplementedError


def _clean_url(url: str) -> str:
    """Resolve a search-result URL to a fetchable absolute http(s) URL.

    DuckDuckGo returns protocol-relative redirect URLs like
    ``//duckduckgo.com/l/?uddg=<urlencoded-real-url>``; decode the real target.
    """
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if "duckduckgo.com/l/" in url and "uddg=" in url:
        try:
            from urllib.parse import parse_qs, unquote, urlparse

            qs = parse_qs(urlparse(url).query)
            if qs.get("uddg"):
                return unquote(qs["uddg"][0])
        except Exception:
            pass
    return url


class DuckDuckGoSearch(SearchBackend):
    """Real search via the engine's WebSearchScraper (no API key)."""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        from compass_collector.scraper.sources.web_search import WebSearchScraper

        try:
            scraper = WebSearchScraper()
            results = scraper.duckduckgo_search(query, max_results=max_results)
            cleaned = []
            for r in results:
                url = _clean_url(r.get("url", ""))
                if url.startswith(("http://", "https://")):
                    cleaned.append({**r, "url": url})
            return cleaned
        except Exception as exc:
            log.warning("DuckDuckGo search failed for %r: %s", query, exc)
            return []


class NullSearch(SearchBackend):
    """No-op search (tests / no network)."""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        return []


class OpenCLISearch(SearchBackend):
    """Discovery via the engine's OpenCLI bridge (HN, Reddit, Dev.to,
    Google Scholar, ArXiv commands). Graceful no-op if opencli is unavailable.

    On first use it resolves opencli via ``ensure_opencli`` — the system binary
    when present, otherwise a Node+OpenCLI bootstrap into the agent volume.
    """

    _opencli: Optional[str] = None

    @classmethod
    def _resolve_opencli(cls) -> str:
        if cls._opencli is None:
            try:
                from compass_agent.opencli_bootstrap import ensure_opencli

                cls._opencli = ensure_opencli()
                if not cls._opencli:
                    log.warning("opencli unavailable — Discovery falls back to other backends")
            except Exception as exc:
                cls._opencli = ""
                log.warning("opencli resolve error: %s", exc)
        return cls._opencli

    def build_queries(self, campaign: Campaign) -> list[str]:
        wf = campaign.workflow.replace("_", " ")
        source_types = set(campaign.source_types)
        cmds: list[str] = []
        # arxiv works headlessly and returns relevant business papers when framed
        # around business process / ROI (e.g. RPA viability frameworks).
        cmds.append(f'arxiv search "business process automation ROI implementation" --limit 8')
        if source_types & {"academic", "peer_reviewed"}:
            cmds.append(f'arxiv search "{wf} evaluation framework business" --limit 6')
        # community adapters are public and cheap; graceful if they return nothing
        cmds.append(f'hackernews search "{wf} ROI" --limit 10')
        cmds.append(f'reddit search "{wf} automation results" --limit 10')
        cmds.append(f'devto search "{wf} implementation" --limit 10')
        return cmds

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        import subprocess

        exe = self._resolve_opencli()
        if not exe:
            return []
        try:
            from compass_agent.opencli_bootstrap import opencli_env

            result = subprocess.run(
                f"{exe} {query} -f json",
                shell=True,
                capture_output=True,
                text=True,
                timeout=45,
                env=opencli_env(),
            )
            if result.returncode != 0:
                return []
            results = json.loads(result.stdout) if result.stdout.strip() else []
        except Exception as exc:
            log.warning("opencli command failed %r: %s", query, exc)
            return []
        out = []
        for item in (results or [])[:max_results]:
            url = (item.get("url") or item.get("link") or "").strip()
            title = (item.get("title") or item.get("name") or item.get("text") or "").strip()
            if url:
                out.append({"url": url, "title": title, "source_type": "opencli"})
        return out


class CuratedSeedSearch(SearchBackend):
    """Curated gold sources (evidence_seeds.yaml) + vendor landings
    (sources.yaml), filtered by relevance to the campaign workflow."""

    def build_queries(self, campaign: Campaign) -> list[str]:
        return [campaign.workflow.replace("_", " ")]

    def _load_seeds(self) -> list[dict]:
        try:
            from pathlib import Path

            import yaml

            base = Path(__file__).resolve().parent.parent.parent
            seeds: list[dict] = []
            for rel in ("compass_collector/config/evidence_seeds.yaml", "compass_collector/config/sources.yaml"):
                path = base / rel
                if not path.exists():
                    continue
                data = yaml.safe_load(path.read_text()) or {}
                if rel.endswith("evidence_seeds.yaml"):
                    for campaign_cfg in (data.get("campaigns") or {}).values():
                        for u in campaign_cfg.get("urls", []):
                            seeds.append({"url": u.get("url", ""), "title": u.get("title", ""), "source_type": "seed"})
                else:
                    for src in (data.get("sources") or {}).values():
                        for landing in src.get("known_landings", []):
                            seeds.append({"url": landing, "title": src.get("root_domain", landing), "source_type": "vendor_landing"})
            return [s for s in seeds if s.get("url")]
        except Exception as exc:
            log.warning("seed load failed: %s", exc)
            return []

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        keywords = set(query.lower().replace("_", " ").split())
        out = []
        for s in self._load_seeds():
            hay = f"{s.get('title', '')} {s.get('url', '')}".lower()
            if keywords and not any(k in hay for k in keywords):
                continue
            out.append(s)
            if len(out) >= max_results:
                break
        return out


class ArxivSearch(SearchBackend):
    """ArXiv API search via the engine's ArxivScraper."""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        try:
            from compass_collector.scraper.sources.arxiv_scraper import ArxivScraper

            results = ArxivScraper().search(query, max_results=max_results)
            return [
                {"url": r.get("url", ""), "title": r.get("title", ""), "source_type": "arxiv"}
                for r in results
                if r.get("url")
            ]
        except Exception as exc:
            log.warning("arxiv search failed for %r: %s", query, exc)
            return []


# ── Fetchers ─────────────────────────────────────────────────────────────

class Fetcher:
    """Protocol: given a URL, return extracted plain text."""

    def fetch(self, url: str, title: str = "") -> str:
        raise NotImplementedError


class HttpFetcher(Fetcher):
    """HTTP fetch + HTML-to-text via bs4 (the engine's parser stack)."""

    def fetch(self, url: str, title: str = "") -> str:
        import httpx
        from bs4 import BeautifulSoup

        if not url.startswith(("http://", "https://")):
            log.warning("skip fetch for non-http URL: %s", url)
            return ""
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "CompassEvidenceAgent/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return " ".join(soup.get_text(" ", strip=True).split())[:12000]
        except Exception as exc:
            log.warning("fetch failed for %s: %s", url, exc)
            return ""


class StubFetcher(Fetcher):
    """Returns a fixed text (tests)."""

    def __init__(self, text: str = "") -> None:
        self.text = text

    def fetch(self, url: str, title: str = "") -> str:
        return self.text or title


# ── Source planning ──────────────────────────────────────────────────────

# Business-ROI framed queries are always part of a campaign's discovery so the
# results are evidence-driven business interventions with measured outcomes,
# not academic algorithm papers.
BUSINESS_ROI_QUERIES = [
    "1000 evidence-driven business interventions that had a successful ROI",
    "business process automation implementation ROI case study",
    "workflow automation cost savings measured results",
    "operational improvement ROI enterprise case study",
    "AI implementation enterprise ROI measured outcomes",
    "process redesign efficiency improvement results",
]


def build_queries(workflow: str, source_types: list[str]) -> list[str]:
    """Build targeted search queries for a campaign.

    Every campaign includes the business-ROI query set plus a workflow-specific
    query framed around ROI / measured results, so discovery targets real
    implementations with outcomes. Academic/arxiv framing is only added when the
    campaign explicitly needs academic evidence.
    """
    queries: list[str] = list(BUSINESS_ROI_QUERIES)
    wf = workflow.replace("_", " ")
    queries.append(f"{wf} automation ROI case study")
    queries.append(f"{wf} implementation measured results")
    source_types = set(source_types or [])
    if source_types & {"academic", "peer_reviewed"}:
        queries.append(f"{wf} business process evaluation framework")
    return list(dict.fromkeys(q for q in queries if q))


class SourcePlanner:
    """Turns a campaign into a ranked list of source candidates using every
    available discovery backend (OpenCLI, DuckDuckGo, curated seeds, arXiv)."""

    def __init__(self, backends: Optional[list] = None, max_per_query: int = 8) -> None:
        self.backends = backends or [DuckDuckGoSearch()]
        self.max_per_query = max_per_query

    def plan(self, campaign: Campaign, max_sources: int = 20) -> list[dict]:
        candidates: dict[str, dict] = {}
        for backend in self.backends:
            if hasattr(backend, "build_queries"):
                queries = backend.build_queries(campaign)
            else:
                queries = build_queries(campaign.workflow, campaign.source_types)
            for q in queries:
                try:
                    results = backend.search(q, max_results=self.max_per_query)
                except Exception as exc:
                    log.warning("backend search failed: %s", exc)
                    results = []
                for result in results:
                    url = (result.get("url") or "").strip()
                    if not url or not url.startswith(("http://", "https://")):
                        continue
                    candidates.setdefault(
                        url,
                        {
                            "url": url,
                            "title": (result.get("title") or "").strip(),
                            "source_type": result.get("source_type", "search"),
                            "query": q,
                        },
                    )
                    if len(candidates) >= max_sources:
                        break
                if len(candidates) >= max_sources:
                    break
            if len(candidates) >= max_sources:
                break
        return list(candidates.values())[:max_sources]


# ── Ingestion to the engine ──────────────────────────────────────────────

class IngestPublisher:
    """Posts a new evidence record to the engine's /api/evidence/ingest."""

    def __init__(self, api_url: str = "", token: str = "", enabled: bool = False) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.enabled = enabled

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.api_url) and bool(self.token)

    def ingest(self, record: dict) -> dict:
        import httpx

        if not self.active:
            return {"accepted": False, "reason": "ingest_disabled"}
        try:
            resp = httpx.post(
                f"{self.api_url}/api/evidence/ingest",
                headers={"X-Compass-Agent-Key": self.token},
                json=record,
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            log.warning("ingest for %s returned %s: %s", record.get("url", ""), resp.status_code, resp.text[:200])
            return {"accepted": False, "reason": f"http_{resp.status_code}"}
        except Exception as exc:
            log.warning("ingest failed for %s: %s", record.get("url", ""), exc)
            return {"accepted": False, "reason": "ingest_error"}


# ── Pipeline ─────────────────────────────────────────────────────────────

@dataclass
class DiscoveryReport:
    workflow: str
    business_function: str
    sources_discovered: int = 0
    accepted: int = 0
    rejected: int = 0
    rich_records_created: int = 0
    cost_usd: float = 0.0
    rejections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "business_function": self.business_function,
            "sources_discovered": self.sources_discovered,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rich_records_created": self.rich_records_created,
            "cost_usd": round(self.cost_usd, 6),
        }


class DiscoveryPipeline:
    def __init__(
        self,
        planner: SourcePlanner,
        fetcher: Fetcher,
        llm,
        ingest: IngestPublisher,
        budget_gate: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.planner = planner
        self.fetcher = fetcher
        self.llm = llm
        self.ingest = ingest
        self.budget_gate = budget_gate

    def run(self, campaign: Campaign, max_sources: int = 10) -> DiscoveryReport:
        report = DiscoveryReport(workflow=campaign.workflow, business_function=campaign.business_function)
        if not self.llm.can_run:
            report.rejections.append("llm_disabled")
            return report

        candidates = self.planner.plan(campaign, max_sources=max_sources)
        report.sources_discovered = len(candidates)

        for candidate in candidates:
            if self.budget_gate is not None and not self.budget_gate():
                report.rejections.append("budget_gate")
                break

            text = self.fetcher.fetch(candidate["url"], candidate.get("title", ""))
            if len(text.strip()) < 120:
                report.rejected += 1
                report.rejections.append("insufficient_text")
                continue

            result = self.llm.enrich(text, title=candidate.get("title", ""), url=candidate["url"])
            report.cost_usd += result.cost

            from compass_agent.validate import validate_enrichment

            validation = validate_enrichment(result.payload)
            if not validation.valid:
                report.rejected += 1
                report.rejections.append("validation")
                continue

            payload = result.payload
            record = {
                "source": "compass_agent:discovery",
                "url": candidate["url"],
                "title": candidate.get("title", ""),
                "organization_name": payload.get("organization_name", ""),
                "organization_industry": [payload.get("organization_industry")] if payload.get("organization_industry") else [],
                "problem_statement": payload.get("business_problem", ""),
                "problem_business_function": [payload.get("business_function", "")] if payload.get("business_function") else [],
                "workflow": payload.get("workflow", campaign.workflow),
                "intervention_title": payload.get("intervention_title", ""),
                "intervention_category": payload.get("intervention_category", ""),
                "intervention_families": [payload.get("intervention_category", "").lower().replace(" ", "_")] if payload.get("intervention_category") else [],
                "evidence_tier": str(payload.get("evidence_tier") or "bronze").lower(),
                "implementation_provenance": (payload.get("evidence_quality") or {}).get("implementation_provenance", ""),
                "outcome_provenance": (payload.get("evidence_quality") or {}).get("outcome_provenance", ""),
                "implementation_fields": {
                    "rollout_strategy": payload.get("rollout_strategy", ""),
                    "success_criteria": payload.get("success_criteria") or [],
                    "lessons_learned": payload.get("lessons_learned") or [],
                    "implementation_pattern": payload.get("implementation_pattern") or [],
                    "pilot_structure": payload.get("pilot_structure", ""),
                    "executive_sponsor": payload.get("executive_sponsor", ""),
                    "governance_model": payload.get("governance_model", ""),
                    "intervention_vendors": payload.get("intervention_vendors") or [],
                },
                "outcomes": payload.get("outcomes") or [],
                "field_provenance": [{"field": k, "source": "llm_extraction", "url": candidate["url"]} for k in ("rollout_strategy", "success_criteria", "lessons_learned", "implementation_pattern")],
            }
            ingest_result = self.ingest.ingest(record)
            if ingest_result.get("accepted"):
                report.accepted += 1
                if ingest_result.get("rich"):
                    report.rich_records_created += 1
            else:
                report.rejected += 1
                report.rejections.append(ingest_result.get("reason", "rejected"))

        # update the campaign
        campaign.discovered += report.sources_discovered
        campaign.accepted += report.accepted
        campaign.rejected += report.rejected
        campaign.rich_records_created += report.rich_records_created
        campaign.cost_usd += report.cost_usd
        return report
