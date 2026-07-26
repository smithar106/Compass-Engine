#!/usr/bin/env python3
"""V3: Fetch case study pages from high-value sources.

Uses smart discovery per source: sitemaps, search, known URL patterns, or OpenCLI browser.
"""

import sys, os, json, time, hashlib, uuid, subprocess, re
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "source_registry.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def load_registry():
    if not REGISTRY_PATH.exists():
        print("ERROR: Source registry not found.")
        sys.exit(1)
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def save_registry(registry):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def run_opencli(cmd: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(f"opencli {cmd}", shell=True,
                                 capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return ""
        return result.stdout
    except:
        return ""


# ── Helper: fetch XML sitemap URLs ──
def fetch_sitemap_urls(sitemap_url: str) -> list:
    try:
        resp = requests.get(sitemap_url, timeout=20, headers={"User-Agent": USER_AGENT})
        if resp.status_code == 200:
            urls = re.findall(r'<loc>(.*?)</loc>', resp.text)
            # Check for sitemap index (nested sitemaps)
            sitemaps = re.findall(r'<loc>(.*?sitemap.*?)</loc>', resp.text, re.IGNORECASE)
            if sitemaps and not urls:
                all_urls = []
                for sm in sitemaps[:10]:
                    all_urls.extend(fetch_sitemap_urls(sm))
                return all_urls
            return urls
    except:
        pass
    return []


# ── Helper: web search for case studies ──
SEARCH_ENGINES = [
    "https://html.duckduckgo.com/html/?q={q}",
]

def web_search_for_case_studies(query: str, max_results: int = 30) -> list:
    """Search the web for case studies matching the given query."""
    results = []
    for engine_tpl in SEARCH_ENGINES:
        url = engine_tpl.replace("{q}", requests.utils.quote(query))
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                h = a["href"]
                if h.startswith("//"):
                    h = "https:" + h
                elif h.startswith("/"):
                    continue
                if h.startswith("http") and len(h) > 25:
                    results.append(h)
        except:
            continue
        if len(results) >= max_results:
            break
    return results[:max_results]


# ── Source-specific URL patterns ──
SOURCE_PATTERNS = {
    # ── Cloud & Enterprise ──
    "AWS Customer Stories": {
        "type": "sitemap",
        "url": "https://aws.amazon.com/solutions/case-studies/",
        "link_pattern": r"https://aws\.amazon\.com/solutions/case-studies/[a-z0-9-]+",
        "allowed_domains": ["aws.amazon.com"],
        "max_per_source": 20,
    },
    "Microsoft Customer Stories": {
        "type": "sitemap",
        "url": "https://customers.microsoft.com/",
        "link_pattern": r"https://customers\.microsoft\.com/[a-z-]+/story/\d+[a-z0-9-]+",
        "allowed_domains": ["customers.microsoft.com"],
        "max_per_source": 20,
    },
    "Google Cloud Customer Stories": {
        "type": "sitemap",
        "url": "https://cloud.google.com/customers",
        "link_pattern": r"https://cloud\.google\.com/customers/[a-z0-9-]+",
        "allowed_domains": ["cloud.google.com"],
        "max_per_source": 20,
    },
    "Oracle Customer Stories": {
        "type": "sitemap",
        "url": "https://www.oracle.com/customers/",
        "link_pattern": r"https://www\.oracle\.com/customers/[a-z0-9-]+",
        "allowed_domains": ["oracle.com"],
        "max_per_source": 20,
    },
    "IBM Customer Stories": {
        "type": "sitemap",
        "url": "https://www.ibm.com/case-studies",
        "link_pattern": r"https://www\.ibm\.com/case-studies/[a-z0-9-]+",
        "allowed_domains": ["ibm.com"],
        "max_per_source": 20,
    },
    "SAP Customer Stories": {
        "type": "web_search",
        "url": "https://www.sap.com/customer-stories.html",
        "search_terms": ["site:sap.com customer story case study"],
        "allowed_domains": ["sap.com"],
        "max_per_source": 15,
    },
    "Snowflake Customer Stories": {
        "type": "sitemap",
        "url": "https://www.snowflake.com/en/customers/all-customers/",
        "link_pattern": r"https://www\.snowflake\.com/[a-z]+/customers/all-customers/case-study/[a-z0-9-]+",
        "allowed_domains": ["snowflake.com"],
        "max_per_source": 20,
    },
    "Databricks Customer Stories": {
        "type": "sitemap_xml",
        "url": "https://www.databricks.com/en-customer-assets/sitemap/sitemap-index.xml",
        "link_pattern": r"https://www\.databricks\.com/[a-z]+/customers/[a-z0-9-]+",
        "allowed_domains": ["databricks.com"],
        "max_per_source": 20,
    },
    "Salesforce Customer Success": {
        "type": "sitemap",
        "url": "https://www.salesforce.com/customer-success-stories/",
        "link_pattern": r"https://www\.salesforce\.com/[a-z-]+/customer-success-stories/",
        "allowed_domains": ["salesforce.com"],
        "max_per_source": 20,
    },
    "ServiceNow Customer Stories": {
        "type": "sitemap",
        "url": "https://www.servicenow.com/customers/",
        "link_pattern": r"https://www\.servicenow\.com/[a-z-]+/customers/.+",
        "allowed_domains": ["servicenow.com"],
        "max_per_source": 20,
    },
    "Cisco Customer Case Studies": {
        "type": "web_search",
        "url": "https://www.cisco.com/c/en/us/solutions/customer-case-studies.html",
        "search_terms": ["site:cisco.com case study customer implementation"],
        "allowed_domains": ["cisco.com"],
        "max_per_source": 15,
    },
    "Workday Customer Stories": {
        "type": "web_search",
        "url": "https://www.workday.com/en-us/customer-stories.html",
        "search_terms": ["site:workday.com customer story implementation"],
        "allowed_domains": ["workday.com"],
        "max_per_source": 15,
    },
    "Adobe Customer Stories": {
        "type": "sitemap_xml",
        "url": "https://business.adobe.com/sitemap.xml",
        "link_pattern": r"https://business\.adobe\.com/customer-success-stories/[a-z0-9-]+",
        "allowed_domains": ["business.adobe.com"],
        "max_per_source": 20,
    },
    "Atlassian Customer Stories": {
        "type": "sitemap",
        "url": "https://www.atlassian.com/customers",
        "link_pattern": r"https://www\.atlassian\.com/customers/[a-z0-9-]+",
        "allowed_domains": ["atlassian.com"],
        "max_per_source": 20,
    },
    "Slack Customer Stories": {
        "type": "sitemap",
        "url": "https://slack.com/customer-stories",
        "link_pattern": r"https://slack\.com/customer-stories/[a-z0-9-]+",
        "allowed_domains": ["slack.com"],
        "max_per_source": 20,
    },
    "Zendesk Customer Stories": {
        "type": "sitemap",
        "url": "https://www.zendesk.com/why-zendesk/customers/",
        "link_pattern": r"https://www\.zendesk\.com/customer/[a-z0-9-]+",
        "allowed_domains": ["zendesk.com"],
        "max_per_source": 20,
    },
    "HubSpot Customer Stories": {
        "type": "web_search",
        "url": "https://www.hubspot.com/customers",
        "search_terms": ["site:hubspot.com customer story case study"],
        "allowed_domains": ["hubspot.com"],
        "max_per_source": 15,
    },

    # ── AI & Automation ──
    "OpenAI Customer Stories": {
        "type": "sitemap",
        "url": "https://openai.com/customer-stories",
        "link_pattern": r"https://openai\.com/[a-z0-9-]+/",
        "allowed_domains": ["openai.com"],
        "max_per_source": 20,
    },
    "Anthropic Customer Stories": {
        "type": "sitemap",
        "url": "https://www.anthropic.com/customer-stories",
        "link_pattern": r"https://www\.anthropic\.com/[a-z0-9-]+",
        "allowed_domains": ["anthropic.com"],
        "max_per_source": 20,
    },
    "Microsoft Copilot Customer Stories": {
        "type": "web_search",
        "url": "https://www.microsoft.com/en-us/microsoft-copilot/customer-stories",
        "search_terms": ["site:microsoft.com copilot customer story implementation"],
        "allowed_domains": ["microsoft.com"],
        "max_per_source": 15,
    },
    "UiPath Case Studies": {
        "type": "sitemap",
        "url": "https://www.uipath.com/resources/automation-case-studies",
        "link_pattern": r"https://www\.uipath\.com/resources/automation-case-studies/[a-z0-9-]+",
        "allowed_domains": ["uipath.com"],
        "max_per_source": 20,
    },
    "Automation Anywhere Case Studies": {
        "type": "sitemap",
        "url": "https://www.automationanywhere.com/resources/customer-stories",
        "link_pattern": r"https://www\.automationanywhere\.com/resources/customer-stories/[a-z0-9-]+",
        "allowed_domains": ["automationanywhere.com"],
        "max_per_source": 20,
    },
    "Blue Prism Customer Stories": {
        "type": "web_search",
        "url": "https://www.blueprism.com/customers/",
        "search_terms": ["site:blueprism.com customer story implementation"],
        "allowed_domains": ["blueprism.com"],
        "max_per_source": 15,
    },

    # ── Consulting & Research ──
    "McKinsey Operations Insights": {
        "type": "search",
        "url": "https://www.mckinsey.com/capabilities/operations/our-insights",
        "allowed_domains": ["mckinsey.com"],
        "max_per_source": 15,
    },
    "Deloitte Insights": {
        "type": "sitemap",
        "url": "https://www.deloitte.com/insights/",
        "allowed_domains": ["deloitte.com"],
        "max_per_source": 20,
    },
    "Accenture Case Studies": {
        "type": "sitemap",
        "url": "https://www.accenture.com/us-en/case-studies",
        "allowed_domains": ["accenture.com"],
        "max_per_source": 20,
    },
    "BCG Publications": {
        "type": "sitemap",
        "url": "https://www.bcg.com/publications",
        "link_pattern": r"https://www\.bcg\.com/publications/\d{4}/[a-z0-9-]+",
        "allowed_domains": ["bcg.com"],
        "max_per_source": 15,
    },
    "Capgemini Case Studies": {
        "type": "sitemap_xml",
        "url": "https://www.capgemini.com/client-story-sitemap.xml",
        "link_pattern": r"https://www\.capgemini\.com/news/client-stories/[a-z0-9-]+",
        "allowed_domains": ["capgemini.com"],
        "max_per_source": 20,
    },
    "PwC Case Studies": {
        "type": "web_search",
        "url": "https://www.pwc.com/gx/en/case-studies.html",
        "search_terms": ["site:pwc.com case study implementation"],
        "allowed_domains": ["pwc.com"],
        "max_per_source": 15,
    },
    "EY Case Studies": {
        "type": "web_search",
        "url": "https://www.ey.com/en_gl/case-studies",
        "search_terms": ["site:ey.com case study implementation transformation"],
        "allowed_domains": ["ey.com"],
        "max_per_source": 15,
    },
    "KPMG Case Studies": {
        "type": "web_search",
        "url": "https://kpmg.com/xx/en/home/insights/case-studies.html",
        "search_terms": ["site:kpmg.com case study implementation"],
        "allowed_domains": ["kpmg.com"],
        "max_per_source": 15,
    },
    "Gartner Case Studies": {
        "type": "web_search",
        "url": "https://www.gartner.com/en/case-studies",
        "search_terms": ["site:gartner.com case study implementation"],
        "allowed_domains": ["gartner.com"],
        "max_per_source": 10,
    },
    "Forrester Case Studies": {
        "type": "sitemap_xml",
        "url": "https://www.forrester.com/client_sitemap.xml",
        "link_pattern": r"https://www\.forrester\.com/report/case-study-[a-z0-9-]+",
        "allowed_domains": ["forrester.com"],
        "max_per_source": 15,
    },
    "IDC Case Studies": {
        "type": "sitemap_xml",
        "url": "https://www.idc.com/client-sitemap.xml",
        "link_pattern": r"https://www\.idc\.com/client/[a-z0-9-]+",
        "allowed_domains": ["idc.com"],
        "max_per_source": 20,
    },

    # ── Government & Public Sector ──
    "NHS Digital Case Studies": {
        "type": "web_search",
        "url": "https://digital.nhs.uk/case-studies",
        "search_terms": ["site:digital.nhs.uk case study implementation"],
        "allowed_domains": ["digital.nhs.uk"],
        "max_per_source": 15,
    },
    "GSA Case Studies": {
        "type": "web_search",
        "url": "https://www.gsa.gov/case-studies",
        "search_terms": ["site:gsa.gov case study implementation"],
        "allowed_domains": ["gsa.gov"],
        "max_per_source": 10,
    },

    # ── Academic ──
    "MIT Sloan Case Studies": {
        "type": "web_search",
        "url": "https://mitsloan.mit.edu/case-studies",
        "search_terms": ["site:mitsloan.mit.edu case study implementation operations"],
        "allowed_domains": ["mitsloan.mit.edu"],
        "max_per_source": 10,
    },
    "Stanford HAI Case Studies": {
        "type": "web_search",
        "url": "https://hai.stanford.edu/case-studies",
        "search_terms": ["site:hai.stanford.edu case study AI implementation"],
        "allowed_domains": ["hai.stanford.edu"],
        "max_per_source": 10,
    },
    "Harvard Business School Case Studies": {
        "type": "web_search",
        "url": "https://www.hbs.edu/case-studies",
        "search_terms": ["site:hbs.edu case study operations implementation"],
        "allowed_domains": ["hbs.edu"],
        "max_per_source": 10,
    },
    "NVIDIA Enterprise Stories": {
        "type": "sitemap",
        "url": "https://www.nvidia.com/en-us/case-studies/",
        "link_pattern": r"https://www\.nvidia\.com/[a-z-]+/case-studies/[a-z0-9-]+",
        "allowed_domains": ["nvidia.com"],
        "max_per_source": 20,
    },
}

# ── Workflow-specific web searches for gap filling ──
WORKFLOW_SEARCHES = [
    # Customer support
    "customer support automation case study reduced handle time",
    "contact center AI implementation results before after",
    "customer service transformation measurable outcomes",
    # Finance & accounting
    "invoice processing automation case study ROI",
    "accounts payable automation results cost savings",
    "financial reconciliation automation case study",
    "insurance claims processing automation results",
    # Sales & marketing
    "sales lead qualification AI case study results",
    "CRM implementation case study sales increase",
    # HR
    "employee onboarding automation case study time savings",
    "HR transformation measurable outcomes case study",
    "recruiting AI case study time to hire reduction",
    # IT & engineering
    "IT service management automation case study",
    "knowledge management implementation case study results",
    "internal knowledge search AI case study",
    # Operations
    "procurement automation case study cost reduction",
    "supply chain optimization case study measurable results",
    "warehouse automation case study productivity increase",
    "field service optimization case study results",
    "workforce scheduling automation case study",
    "maintenance optimization predictive case study results",
    "inventory planning AI case study results",
    "demand forecasting machine learning case study",
    # Cross-functional
    "fraud detection AI case study results savings",
    "contract review AI automation case study",
    "document processing automation case study",
    "data entry automation case study time saved",
    "quality assurance automation case study",
    "compliance review automation case study results",
    "process redesign Lean Six Sigma case study results",
    "RPA implementation case study ROI hours saved",
    # Failure/risk
    "automation implementation failure lessons learned",
    "digital transformation failed case study lessons",
    "AI implementation challenges case study",
]


def fetch_page_direct(url: str) -> str:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except:
        return ""


def extract_links_from_html(url: str, allowed_domains: list = None, pattern: str = None) -> list:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif not href.startswith("http"):
                href = urljoin(url, href)
            if allowed_domains:
                parsed = urlparse(href)
                if not any(d in parsed.netloc for d in allowed_domains):
                    continue
            if pattern:
                if not re.search(pattern, href, re.IGNORECASE):
                    continue
            links.add(href)
        return sorted(links)
    except:
        return []


def fetch_with_opencli(url: str) -> str:
    return run_opencli(f"web read --url '{url}'", timeout=45)


def discover_case_studies(source: dict) -> list[dict]:
    source_name = source.get("source_name", "")
    pattern_cfg = SOURCE_PATTERNS.get(source_name, {})

    if not pattern_cfg:
        return []

    source_type = pattern_cfg.get("type", "sitemap")
    list_url = pattern_cfg.get("url", source.get("discovery_url", ""))
    allowed_domains = pattern_cfg.get("allowed_domains", [])
    link_pattern = pattern_cfg.get("link_pattern", "")
    max_per_source = pattern_cfg.get("max_per_source", 20)
    search_terms = pattern_cfg.get("search_terms", [])

    if not list_url:
        return []

    print(f"  Discovering from: {list_url}")

    links = []

    if source_type == "sitemap_xml":
        all_urls = fetch_sitemap_urls(list_url)
        for u in all_urls:
            if link_pattern and not re.search(link_pattern, u, re.IGNORECASE):
                continue
            if allowed_domains and not any(d in urlparse(u).netloc for d in allowed_domains):
                continue
            links.append(u)

    elif source_type == "web_search":
        for term in search_terms:
            results = web_search_for_case_studies(term, max_results=15)
            for u in results:
                if link_pattern and not re.search(link_pattern, u, re.IGNORECASE):
                    continue
                if allowed_domains and not any(d in urlparse(u).netloc for d in allowed_domains):
                    continue
                links.append(u)

    elif source_type == "sitemap":
        links = extract_links_from_html(list_url, allowed_domains, link_pattern)
        if not links:
            text = fetch_with_opencli(list_url)
            if text and len(text) > 200:
                urls_in_text = re.findall(r'https?://[^\s"\'<>]+', text)
                if link_pattern:
                    urls_in_text = [u for u in urls_in_text if re.search(link_pattern, u)]
                if allowed_domains:
                    urls_in_text = [u for u in urls_in_text
                                    if any(d in urlparse(u).netloc for d in allowed_domains)]
                links = urls_in_text
    else:
        text = fetch_with_opencli(list_url)
        links = re.findall(r'https?://[^\s"\'<>]+', text) if text else []
        if allowed_domains:
            links = [u for u in links if any(d in urlparse(u).netloc for d in allowed_domains)]

    # Deduplicate
    links = list(dict.fromkeys(links))

    case_studies = []
    for url in links[:max_per_source]:
        try:
            title_resp = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
            title_soup = BeautifulSoup(title_resp.text, "html.parser")
            title = title_soup.title.string.strip() if title_soup.title else ""
            title = title[:200] if title else url.split("/")[-1].replace("-", " ").title()
        except:
            title = url.split("/")[-1].replace("-", " ").title()
        case_studies.append({"url": url, "title": title})

    return case_studies


def fetch_and_save(source: dict, case_study: dict, output_dir: Path, session_name: str) -> dict:
    url = case_study["url"]
    title = case_study["title"]

    text = fetch_page_direct(url)
    if not text or len(text) < 200:
        article = run_opencli(f"browser {session_name} open '{url}' --window background && sleep 3 && browser {session_name} extract", timeout=60)
        text = article if article else ""
        run_opencli(f"browser {session_name} close", timeout=5)
    if not text or len(text) < 200:
        text = fetch_with_opencli(url)
    if not text or len(text) < 200:
        return {"url": url, "status": "failed", "reason": "insufficient_content"}

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

    doc_record = {
        "id": doc_id,
        "url": url,
        "title": title[:500],
        "content_hash": content_hash,
        "cleaned_text": text[:15000],
        "source_registry_id": source.get("id", ""),
        "source_name": source.get("source_name", ""),
        "crawl_status": "success",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "generation": "v3",
    }

    out_file = output_dir / f"{doc_id}.json"
    with open(out_file, "w") as f:
        json.dump(doc_record, f)

    return {"url": url, "status": "success", "doc_id": doc_id, "text_length": len(text)}


def main():
    registry = load_registry()
    output_dir = Path(__file__).resolve().parent.parent / "data" / "v3_fetched"
    output_dir.mkdir(parents=True, exist_ok=True)

    enabled = {k: v for k, v in registry.items() if v.get("enabled", False)}
    enabled = dict(sorted(enabled.items(), key=lambda x: x[1].get("priority", 5)))

    total_discovered = 0
    total_fetched = 0
    total_failed = 0
    session_name = "v3fetch"

    run_opencli(f"browser {session_name} init", timeout=10)

    for sid, source in enabled.items():
        source_name = source.get("source_name", "unknown")
        print(f"\n=== {source_name} ===")

        if source_name not in SOURCE_PATTERNS:
            print(f"  SKIP (no discovery pattern configured)")
            continue

        discovered = discover_case_studies(source)
        print(f"  Discovered: {len(discovered)} case study links")
        total_discovered += len(discovered)
        source["case_studies_discovered"] = len(discovered)

        for cs in discovered[:20]:
            result = fetch_and_save(source, cs, output_dir, session_name)
            if result["status"] == "success":
                total_fetched += 1
                print(f"  [OK] {cs['title'][:80]}")
            else:
                total_failed += 1
                print(f"  [--] {cs['title'][:80]}: {result.get('reason', 'failed')}")
            time.sleep(0.3)

        source["last_crawl"] = datetime.now(timezone.utc).isoformat()
        save_registry(registry)

    run_opencli(f"browser {session_name} close", timeout=5)

    print(f"\n{'='*60}")
    print(f"Discovered: {total_discovered}")
    print(f"Fetched:    {total_fetched}")
    print(f"Failed:     {total_failed}")
    print(f"Output:     {output_dir}")


if __name__ == "__main__":
    main()
