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
import re
import time
import urllib.parse
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional

from compass_agent.campaign import Campaign

log = logging.getLogger("compass_agent.discovery")

# Degraded-source circuit breaker (process-global so it survives the per-cycle
# instantiation of backends). When a source is blocked (HTTP 403, Cloudflare,
# etc.) it is marked degraded after N consecutive failures and skipped for a
# retry interval instead of being hammered every single cycle.
_DEGRADED_UNTIL: dict[str, float] = {}
_DEGRAD_FAILS: dict[str, int] = {}
_DEGRADED_LOGGED: set[str] = set()


class DegradedBackend:
    """Circuit breaker for flaky/blocked search sources.

    ``name`` must identify the source. After `max_fails` consecutive failures
    the backend stops answering until a retry interval elapses, then makes one
    attempt to recover. Improves log hygiene and avoids wasting requests on
    sources that are currently being blocked.
    """

    name = "degraded"
    retry_seconds: float = 1800.0
    max_fails: int = 2

    def _in_cooldown(self, query: str) -> bool:
        until = _DEGRADED_UNTIL.get(self.name, 0.0)
        if time.time() < until:
            # Log once per cooldown window, not once per cycle.
            if self.name not in _DEGRADED_LOGGED:
                _DEGRADED_LOGGED.add(self.name)
                log.warning(
                    "%s is degraded (repeated failures) — backing off for %.0fs.",
                    self.name, until - time.time(),
                )
            return True
        _DEGRADED_LOGGED.discard(self.name)
        return False

    def _mark_fail(self) -> None:
        fails = _DEGRAD_FAILS.get(self.name, 0) + 1
        if fails >= self.max_fails:
            _DEGRADED_UNTIL[self.name] = time.time() + self.retry_seconds
            _DEGRAD_FAILS[self.name] = 0
        else:
            _DEGRAD_FAILS[self.name] = fails

    def _mark_ok(self) -> None:
        _DEGRAD_FAILS[self.name] = 0
        _DEGRADED_UNTIL.pop(self.name, None)
        _DEGRADED_LOGGED.discard(self.name)


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

    def build_queries(self, campaign: Campaign) -> list[str]:
        """Shopping-list hunts run the composed queries; otherwise generic ROI."""
        terms = getattr(campaign, "search_terms", None)
        if terms:
            return list(terms)
        return build_queries(campaign.workflow, campaign.source_types)

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


class HackerNewsSearch(SearchBackend):
    """HackerNews via Algolia API — free, no key, returns stories with URLs."""

    def search(self, query: str, max_results: int = 25) -> list[dict]:
        try:
            params = urllib.parse.urlencode({"query": query, "hitsPerPage": max_results, "tags": "story"})
            url = f"https://hn.algolia.com/api/v1/search?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "CompassAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            out = []
            for hit in data.get("hits", [])[:max_results]:
                u = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                if u.startswith(("http://", "https://")):
                    out.append({"url": u, "title": hit.get("title", ""), "source_type": "hackernews"})
            return out
        except Exception as exc:
            log.warning("HN search failed %r: %s", query, exc)
            return []


class RedditSearch(SearchBackend, DegradedBackend):
    """Reddit via JSON API — searches across Reddit for implementation
    discussions. Currently frequently blocked (HTTP 403); guarded by the
    degraded-source circuit breaker so it backs off instead of spamming."""

    name = "reddit"
    retry_seconds = 1800.0

    def search(self, query: str, max_results: int = 25) -> list[dict]:
        if self._in_cooldown(query):
            return []
        try:
            params = urllib.parse.urlencode({"q": query, "limit": max_results, "sort": "relevance"})
            url = f"https://www.reddit.com/search.json?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "CompassAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            out = []
            for child in data.get("data", {}).get("children", [])[:max_results]:
                d = child.get("data", {})
                u = d.get("url", "")
                if u.startswith(("http://", "https://")):
                    out.append({"url": u, "title": d.get("title", ""), "source_type": "reddit"})
            if out:
                self._mark_ok()
            return out
        except Exception as exc:
            log.warning("Reddit search failed %r: %s", query, exc)
            self._mark_fail()
            return []


class CommunitySearch(SearchBackend):
    """Aggregates HN + Reddit + Medium searches for broader discovery."""

    def build_queries(self, campaign: Campaign) -> list[str]:
        wf = campaign.workflow.replace("_", " ")
        return [wf, f"{wf} implementation results", f"{wf} ROI case study"]

    def search(self, query: str, max_results: int = 15) -> list[dict]:
        results = []
        for backend in (HackerNewsSearch(), RedditSearch(), MediumSearch()):
            try:
                results.extend(backend.search(query, max_results=max_results // 3))
            except Exception:
                pass
        return results


class MediumSearch(SearchBackend, DegradedBackend):
    """Medium article search via unofficial JSON feed — no API key needed.
    Currently frequently blocked (HTTP 403); guarded by the degraded-source
    circuit breaker so it backs off instead of spamming."""

    name = "medium"
    retry_seconds = 1800.0

    def search(self, query: str, max_results: int = 15) -> list[dict]:
        if self._in_cooldown(query):
            return []
        try:
            params = urllib.parse.urlencode({"q": query})
            url = f"https://medium.com/search?{params}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "CompassAgent/1.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode()
            # Medium embeds search results in script tags; extract any URLs
            out = []
            seen = set()
            for match in re.finditer(r'"postId":"(\w+)",[^}]*"title":"([^"]+)"', text):
                pid, title = match.group(1), match.group(2)
                u = f"https://medium.com/p/{pid}"
                if u not in seen:
                    seen.add(u)
                    out.append({"url": u, "title": title, "source_type": "medium"})
                    if len(out) >= max_results:
                        break
            if out:
                self._mark_ok()
            return out
        except Exception as exc:
            log.warning("Medium search failed %r: %s", query, exc)
            self._mark_fail()
            return []


class GoogleSearch(SearchBackend):
    """High-volume web search for ROI case studies using DuckDuckGo.
    Uses the existing Python scraper — no OpenCLI or browser dependency."""

    _index = 0

    def build_queries(self, campaign: Campaign) -> list[str]:
        wf = campaign.workflow.replace("_", " ")
        # Rotate through ROI queries in blocks so DDG returns fresh results
        # instead of the same cached pages every cycle.
        block_size = 12
        start = (self._index % (len(ROI_QUERIES) // block_size)) * block_size
        end = start + block_size
        queries = ROI_QUERIES[start:end]
        if len(queries) < block_size:
            queries += ROI_QUERIES[:block_size - len(queries)]
        # Add date-anchored variants to force fresh SERP
        years = ["2024", "2025", "2026"]
        year = years[self._index % 3]
        varied = []
        for q in queries:
            varied.append(f"{q} {year}")
            varied.append(q)
        GoogleSearch._index += 1
        return [wf] + varied

    def search(self, query: str, max_results: int = 50) -> list[dict]:
        from compass_collector.scraper.sources.web_search import WebSearchScraper

        try:
            scraper = WebSearchScraper()
            results = scraper.duckduckgo_search(query, max_results=max_results)
            out = []
            for r in results:
                url = _clean_url(r.get("url", ""))
                if url.startswith(("http://", "https://")):
                    out.append({"url": url, "title": r.get("title", ""), "source_type": "ddg"})
            return out
        except Exception as exc:
            log.warning("DDG search failed %r: %s", query, exc)
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
        cmds: list[str] = []
        # Community + academic adapters (headless — no browser needed)
        cmds.append(f'hackernews search "{wf} implementation case study" --limit 15')
        cmds.append(f'reddit search "{wf} ROI results enterprise" --limit 15')
        cmds.append(f'devto search "{wf} implementation" --limit 10')
        cmds.append(f'google-scholar search "{wf} business implementation outcomes" --limit 10')
        cmds.append(f'medium search "{wf} case study measured results" --limit 10')
        cmds.append(f'wikipedia search "{wf} business process" --limit 5')
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
            return " ".join(soup.get_text(" ", strip=True).split())[:40000]
        except Exception as exc:
            log.warning("fetch failed for %s: %s", url, exc)
            return ""

    def fetch_links(self, url: str, title: str = "") -> list[dict]:
        """Extract same-domain article links likely to be individual case
        studies, so an index/landing page can be expanded into its articles."""
        import httpx
        from urllib.parse import urljoin, urlparse

        from bs4 import BeautifulSoup

        if not url.startswith(("http://", "https://")):
            return []
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "CompassEvidenceAgent/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []
        base_host = urlparse(url).netloc.replace("www.", "")
        markers = ("case-study", "case_study", "case study", "customer", "stories", "story", "success")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            absolute = urljoin(url, href)
            parsed = urlparse(absolute)
            host = parsed.netloc.replace("www.", "")
            if host != base_host:
                continue
            path = parsed.path.lower()
            if not any(m in path for m in markers):
                continue
            links.append({"url": absolute, "title": a.get_text(" ", strip=True)[:160]})
        # de-dup by url
        seen = set()
        out = []
        for l in links:
            if l["url"] not in seen:
                seen.add(l["url"])
                out.append(l)
        return out[:20]


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

# Comprehensive ROI case study queries covering all intervention types ×
# industries. Each query targets implementation evidence with measurable
# business outcomes. Used by Google search for high-volume discovery.
ROI_QUERIES = [
    # ─── CROSS-INDUSTRY ROI CASE STUDIES ───
    "enterprise digital transformation ROI case study measured results",
    "operational efficiency improvement cost savings case study",
    "business process automation ROI before after metrics",
    "technology implementation enterprise success metrics case study",
    "organizational transformation ROI quantitative results",
    "IT modernization cost reduction case study enterprise",
    "system migration cost savings implementation results",
    "process optimization ROI case study manufacturing retail finance",
    "workflow automation return on investment enterprise case study",
    "digital operations transformation measured outcomes company",
    # ─── AI & MACHINE LEARNING ───
    "AI implementation ROI enterprise case study measured outcomes",
    "machine learning deployment cost savings business results",
    "generative AI enterprise adoption ROI case study 2024 2025",
    "AI customer service automation ROI contact center case study",
    "artificial intelligence supply chain optimization ROI results",
    "AI fraud detection implementation ROI banking financial services",
    "machine learning predictive maintenance ROI manufacturing case study",
    "AI inventory management optimization cost savings retail",
    "natural language processing enterprise ROI case study",
    "computer vision quality inspection manufacturing ROI results",
    "AI underwriting claims processing insurance ROI case study",
    "recommender system ecommerce revenue uplift case study ROI",
    "AI dynamic pricing optimization revenue increase case study",
    "chatbot customer support cost reduction implementation ROI",
    "AI document processing accounts payable automation ROI results",
    # ─── CLOUD & INFRASTRUCTURE ───
    "cloud migration cost savings enterprise case study before after",
    "on-premise to cloud total cost of ownership reduction case study",
    "AWS migration cost savings enterprise implementation results",
    "Azure cloud adoption enterprise ROI case study",
    "Google Cloud migration cost optimization case study results",
    "hybrid cloud infrastructure implementation ROI enterprise",
    "cloud-native modernization cost savings case study enterprise",
    "serverless architecture migration cost reduction case study",
    "Kubernetes container orchestration ROI implementation enterprise",
    "cloud storage optimization cost savings enterprise case study",
    # ─── SOFTWARE & ERP ───
    "ERP implementation ROI enterprise case study measured results",
    "SAP implementation cost savings operational efficiency case study",
    "Oracle ERP cloud migration ROI case study enterprise",
    "CRM implementation ROI sales productivity increase case study",
    "Salesforce deployment revenue uplift case study enterprise",
    "ServiceNow implementation IT service management ROI results",
    "Workday HR transformation ROI enterprise case study",
    "HRIS cloud migration cost savings implementation results",
    "financial software implementation ROI accounting efficiency",
    "procurement automation software implementation ROI case study",
    # ─── RPA & AUTOMATION ───
    "robotic process automation RPA implementation ROI case study",
    "RPA finance accounting automation cost savings enterprise",
    "RPA healthcare claims processing automation ROI results",
    "RPA banking insurance back office automation ROI case study",
    "intelligent document processing automation ROI results",
    "workflow automation low code no code platform ROI case study",
    "business process management BPM implementation ROI results",
    "automation center of excellence ROI enterprise case study",
    "hyperautomation implementation enterprise ROI measured results",
    "RPA shared services center automation cost savings case study",
    # ─── DATA & ANALYTICS ───
    "data warehouse modernization ROI enterprise case study",
    "Snowflake migration cost savings analytics performance case study",
    "data lake implementation enterprise ROI analytics results",
    "business intelligence deployment ROI decision making case study",
    "advanced analytics implementation revenue impact case study",
    "real-time data streaming platform implementation ROI enterprise",
    "data governance framework implementation ROI compliance case study",
    "master data management implementation ROI enterprise results",
    "customer data platform deployment marketing ROI case study",
    "self-service analytics adoption ROI enterprise measured results",
    # ─── CYBERSECURITY ───
    "cybersecurity investment ROI breach prevention cost savings",
    "zero trust architecture implementation ROI enterprise case study",
    "security operations center SOC transformation ROI results",
    "identity access management implementation ROI enterprise case study",
    "endpoint detection response EDR ROI security case study",
    "cloud security posture management CSPM ROI enterprise results",
    "security awareness training ROI phishing reduction metrics",
    "data loss prevention implementation ROI enterprise case study",
    "SIEM modernization Splunk migration ROI security operation results",
    "ransomware preparedness investment ROI enterprise case study",
    # ─── DEV OPS & SOFTWARE DELIVERY ───
    "DevOps transformation ROI deployment frequency quality metrics",
    "CI/CD pipeline implementation ROI software delivery enterprise",
    "platform engineering internal developer portal ROI case study",
    "value stream management implementation ROI enterprise software",
    "test automation ROI quality engineering cost savings case study",
    "site reliability engineering SRE implementation ROI results",
    "gitops deployment automation ROI enterprise case study",
    "feature flag experimentation platform ROI revenue impact",
    "chaos engineering resilience investment ROI enterprise results",
    "developer experience platform investment ROI productivity metrics",
    # ─── CUSTOMER EXPERIENCE ───
    "customer experience improvement ROI revenue impact case study",
    "call center modernization omnichannel ROI case study enterprise",
    "customer self-service portal ROI cost reduction implementation",
    "customer journey mapping personalization ROI conversion uplift",
    "voice of customer program ROI retention revenue case study",
    "Net Promoter Score improvement initiative ROI enterprise results",
    "customer onboarding automation ROI churn reduction case study",
    "loyalty program redesign ROI customer lifetime value case study",
    "digital customer service transformation ROI contact center",
    "customer success platform implementation ROI retention results",
    # ─── SUPPLY CHAIN & LOGISTICS ───
    "supply chain optimization ROI cost reduction enterprise case study",
    "logistics automation warehouse management ROI implementation results",
    "inventory optimization system implementation ROI retail case study",
    "transportation management system TMS implementation ROI logistics",
    "supply chain visibility platform implementation ROI enterprise",
    "demand forecasting AI implementation ROI inventory reduction",
    "last mile delivery optimization ROI transportation case study",
    "procurement digital transformation ROI savings enterprise",
    "supplier relationship management implementation ROI results",
    "supply chain risk management investment ROI resilience case study",
    # ─── MANUFACTURING & INDUSTRY ───
    "smart factory Industry 4.0 implementation ROI manufacturing",
    "lean manufacturing transformation ROI cost savings case study",
    "digital twin implementation ROI manufacturing enterprise",
    "IoT predictive maintenance deployment ROI manufacturing results",
    "quality management system QMS implementation ROI case study",
    "manufacturing execution system MES implementation ROI results",
    "energy management optimization ROI manufacturing cost savings",
    "asset performance management implementation ROI enterprise",
    "connected worker platform implementation ROI manufacturing",
    "3D printing additive manufacturing adoption ROI case study",
    # ─── HEALTHCARE ───
    "healthcare digital transformation ROI patient outcomes case study",
    "EHR optimization implementation ROI healthcare provider results",
    "telemedicine platform implementation ROI patient access results",
    "healthcare revenue cycle management RCM optimization ROI",
    "hospital operations automation ROI cost efficiency case study",
    "clinical workflow automation implementation ROI healthcare",
    "population health management platform ROI outcomes case study",
    "patient engagement platform implementation ROI healthcare",
    "value-based care transformation ROI healthcare organization",
    "healthcare interoperability implementation ROI data sharing",
    # ─── FINANCIAL SERVICES ───
    "banking digital transformation ROI customer experience case study",
    "fintech implementation ROI financial services case study",
    "core banking system modernization ROI cost reduction results",
    "payment processing optimization ROI merchant implementation",
    "wealth management platform implementation ROI advisory results",
    "trade processing automation ROI investment bank case study",
    "regulatory compliance automation regtech ROI financial services",
    "insurance claims automation implementation ROI case study",
    "mortgage processing digital transformation ROI lending results",
    "KYC AML compliance automation implementation ROI banking",
    # ─── RETAIL & E-COMMERCE ───
    "retail digital transformation ROI omnichannel case study",
    "ecommerce platform replatforming ROI revenue uplift results",
    "point of sale modernization implementation ROI retail",
    "retail store technology implementation ROI associate productivity",
    "omnichannel fulfillment BOPIS implementation ROI retail",
    "retail workforce management implementation ROI labor optimization",
    "dynamic pricing retail implementation ROI margin case study",
    "retail returns optimization implementation ROI cost reduction",
    "curbside pickup implementation ROI grocery retail case study",
    "retail media network personalization ROI revenue case study",

    # ─── BROAD DIVERSITY QUERIES (cast wider net) ───
    "enterprise software implementation cost reduction results",
    "technology modernization ROI before after metrics",
    "business transformation success story measured outcomes",
    "operations management improvement ROI case study",
    "strategic initiative results enterprise implementation",
    "productivity improvement technology deployment metrics",
    "cost reduction initiative results enterprise case study",
    "digital innovation implementation outcomes measured",
    "performance improvement program results enterprise",
    "change management technology adoption ROI results",
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
    available discovery backend (DuckDuckGo, curated seeds, OpenCLI, arXiv).

    Backends are consulted in priority order and each is capped so a single
    backend (e.g. arxiv) cannot monopolize the budget with low-value results.
    """

    def __init__(self, backends: Optional[list] = None, max_per_query: int = 8) -> None:
        self.backends = backends or [
            GoogleSearch(),
            DuckDuckGoSearch(),
            CommunitySearch(),
            CuratedSeedSearch(),
        ]
        self.max_per_query = max_per_query

    def plan(self, campaign: Campaign, max_sources: int = 200) -> list[dict]:
        candidates: dict[str, dict] = {}
        for backend in self.backends:
            if len(candidates) >= max_sources:
                break
            added = 0
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
                    if url not in candidates:
                        candidates[url] = {
                            "url": url,
                            "title": (result.get("title") or "").strip(),
                            "source_type": result.get("source_type", "search"),
                            "query": q,
                        }
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
class SourceStats:
    """Per-source discovery metrics so we can tell whether a source actually
    contributes net-new, high-quality evidence before investing in it."""

    name: str
    discovered: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    cost_usd: float = 0.0
    tiers: dict = field(default_factory=dict)  # quality tier → count
    organizations: set = field(default_factory=set)
    industries: set = field(default_factory=set)

    @property
    def acceptance_rate(self) -> float:
        total = self.accepted + self.rejected
        return (self.accepted / total) if total else 0.0

    @property
    def cost_per_accepted(self) -> float:
        return (self.cost_usd / self.accepted) if self.accepted else 0.0

    def to_dict(self) -> dict:
        return {
            "source": self.name,
            "discovered": self.discovered,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "acceptance_rate": round(self.acceptance_rate, 3),
            "cost_usd": round(self.cost_usd, 6),
            "cost_per_accepted": round(self.cost_per_accepted, 6),
            "tiers": self.tiers,
            "unique_organizations": len(self.organizations),
            "unique_industries": len(self.industries),
        }


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
    sources: dict = field(default_factory=dict)

    def _source(self, name: str) -> SourceStats:
        name = name or "unknown"
        return self.sources.setdefault(name, SourceStats(name=name))

    def source_report(self) -> list[dict]:
        return [
            s.to_dict()
            for s in sorted(self.sources.values(), key=lambda s: s.accepted, reverse=True)
        ]

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "business_function": self.business_function,
            "sources_discovered": self.sources_discovered,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rich_records_created": self.rich_records_created,
            "cost_usd": round(self.cost_usd, 6),
            "source_report": self.source_report(),
        }


class DiscoveryPipeline:
    def __init__(
        self,
        planner: SourcePlanner,
        fetcher: Fetcher,
        llm,
        ingest: IngestPublisher,
        budget_gate: Optional[Callable[[], bool]] = None,
        max_implementations_per_source: int = 3,
    ) -> None:
        self.planner = planner
        self.fetcher = fetcher
        self.llm = llm
        self.ingest = ingest
        self.budget_gate = budget_gate
        self.max_implementations_per_source = max_implementations_per_source
        self._seen: set[str] = set()

    def _ingest_payload(self, payload: dict, candidate: dict, campaign: Campaign, report: DiscoveryReport) -> None:
        from compass_agent.validate import validate_enrichment

        source = report._source(candidate.get("source_type", ""))
        validation = validate_enrichment(payload)
        if not validation.valid:
            report.rejected += 1
            report.rejections.append("validation")
            source.rejected += 1
            return
        record = {
            "source": "compass_agent:discovery",
            "url": candidate["url"],
            "title": candidate.get("title", ""),
            "organization_name": payload.get("organization_name", ""),
            "organization_industry": [payload.get("organization_industry")] if payload.get("organization_industry") else [],
            "problem_statement": payload.get("business_problem", ""),
            "problem_business_function": [payload.get("business_function", "")] if payload.get("business_function") else [],
            "workflow": payload.get("workflow") or (campaign.workflow if campaign else ""),
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
            source.accepted += 1
            tier = str(record.get("evidence_tier") or "bronze").lower()
            source.tiers[tier] = source.tiers.get(tier, 0) + 1
            org = record.get("organization_name") or ""
            if org:
                source.organizations.add(org)
            for ind in record.get("organization_industry") or []:
                if ind:
                    source.industries.add(ind)
            if ingest_result.get("rich"):
                report.rich_records_created += 1
        else:
            report.rejected += 1
            report.rejections.append(ingest_result.get("reason", "rejected"))
            source.rejected += 1

    def _extract_and_ingest(self, text: str, candidate: dict, campaign: Campaign, report: DiscoveryReport) -> bool:
        """Run single + (fallback) multi extraction over a page; ingest any
        accepted implementations. Returns True if at least one was accepted."""
        if self.budget_gate is not None and not self.budget_gate():
            report.rejections.append("budget_gate")
            return False

        result = self.llm.enrich(text, title=candidate.get("title", ""), url=candidate["url"])
        report.cost_usd += result.cost
        report._source(candidate.get("source_type", "")).cost_usd += result.cost

        from compass_agent.validate import validate_enrichment

        validation = validate_enrichment(result.payload)
        if validation.valid:
            self._ingest_payload(result.payload, candidate, campaign, report)
            return True

        # Roundup/summary page: mine multiple implementations.
        if self.budget_gate is not None and not self.budget_gate():
            report.rejections.append("budget_gate")
            return False
        many = self.llm.enrich_many(text, title=candidate.get("title", ""), url=candidate["url"])
        if not many:
            report.rejected += 1
            report.rejections.append("no_implementations")
            report._source(candidate.get("source_type", "")).rejected += 1
            return False
        report.cost_usd += many[0].cost
        report._source(candidate.get("source_type", "")).cost_usd += many[0].cost
        before = report.accepted
        ingested = 0
        for item in many:
            if ingested >= self.max_implementations_per_source:
                break
            self._ingest_payload(item.payload, candidate, campaign, report)
            ingested += 1
        return report.accepted > before

    def run(self, campaign: Campaign, max_sources: int = 10) -> DiscoveryReport:
        report = DiscoveryReport(workflow=campaign.workflow, business_function=campaign.business_function)
        if not self.llm.can_run:
            report.rejections.append("llm_disabled")
            return report

        candidates = self.planner.plan(campaign, max_sources=max_sources)
        report.sources_discovered = len(candidates)

        for candidate in candidates:
            source = report._source(candidate.get("source_type", ""))
            source.discovered += 1
            if self.budget_gate is not None and not self.budget_gate():
                report.rejections.append("budget_gate")
                break

            url = candidate["url"]
            if url in self._seen:
                report.rejected += 1
                report.rejections.append("cross_cycle_duplicate")
                source.rejected += 1
                source.duplicates += 1
                continue

            before = report.accepted
            text = self.fetcher.fetch(url, candidate.get("title", ""))
            self._seen.add(url)
            if len(text.strip()) < 120:
                report.rejected += 1
                report.rejections.append("insufficient_text")
                source.rejected += 1
                self._expand(candidate, campaign, report)
                continue

            self._extract_and_ingest(text, candidate, campaign, report)
            # nothing accepted from this page → it may be an index; follow links
            if report.accepted == before:
                self._expand(candidate, campaign, report)

        # update the campaign
        campaign.discovered += report.sources_discovered
        campaign.accepted += report.accepted
        campaign.rejected += report.rejected
        campaign.rich_records_created += report.rich_records_created
        campaign.cost_usd += report.cost_usd
        return report

    def _expand(self, candidate: dict, campaign: Campaign, report: DiscoveryReport) -> None:
        """Follow same-domain case-study links from an index/landing page."""
        fetcher = getattr(self.fetcher, "fetch_links", None)
        if fetcher is None:
            return
        try:
            links = fetcher(candidate["url"], candidate.get("title", ""))
        except Exception as exc:
            log.warning("link expansion failed for %s: %s", candidate["url"], exc)
            return
        for link in links[: self.max_implementations_per_source]:
            if self.budget_gate is not None and not self.budget_gate():
                break
            if link["url"] in self._seen:
                continue
            link["source_type"] = link.get("source_type") or candidate.get("source_type", "")
            link_text = self.fetcher.fetch(link["url"], link.get("title", ""))
            self._seen.add(link["url"])
            if len(link_text.strip()) < 120:
                continue
            report.sources_discovered += 1
            report._source(candidate.get("source_type", "")).discovered += 1
            self._extract_and_ingest(link_text, link, campaign, report)
