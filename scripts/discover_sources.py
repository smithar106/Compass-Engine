#!/usr/bin/env python3
"""Evidence source discovery engine.

Discovers live case study/implementation URLs from configured sources
using sitemaps, landing pages, and navigation crawling.

Usage:
    python scripts/discover_sources.py --discover           # Run discovery for all sources
    python scripts/discover_sources.py --source uipath      # Single source
    python scripts/discover_sources.py --validate           # Validate discovered URLs
    python scripts/discover_sources.py --report             # Summary report
    python scripts/discover_sources.py --pilot              # Pilot: 10-25 per source
"""

import sys, os, json, time, hashlib, yaml, re, logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("discover")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.config.settings import REGISTRY_DIR, CACHE_DIR


class SourceRegistry:
    """Loads and manages source configurations."""

    def __init__(self, path: str = None):
        if not path:
            path = Path(__file__).resolve().parent.parent / "compass_collector" / "config" / "sources.yaml"
        with open(path) as f:
            self.config = yaml.safe_load(f)
        self.sources = self.config.get("sources", {})

    def list_sources(self) -> list[str]:
        return list(self.sources.keys())

    def get(self, name: str) -> dict:
        return self.sources.get(name, {})


class URLValidator:
    """Validates URLs before adding to the ingestion queue."""

    def __init__(self):
        self.cache_dir = CACHE_DIR / "url_validation"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def validate(self, url: str, method: str = "requests") -> dict:
        cache_path = self.cache_dir / f"{hashlib.md5(url.encode()).hexdigest()}.json"
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)

        result = {"original_url": url, "final_url": "", "status": 0, "content_type": "", "content_hash": "", "body_length": 0, "valid": False, "error": ""}

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            body = resp.read()
            result["final_url"] = resp.url
            result["status"] = resp.status
            result["content_type"] = resp.headers.get("Content-Type", "")
            result["body_length"] = len(body)
            result["content_hash"] = hashlib.sha256(body).hexdigest()[:16]
            result["valid"] = resp.status == 200 and len(body) > 500
        except Exception as e:
            result["error"] = str(e)[:80]

        with open(cache_path, "w") as f:
            json.dump(result, f)
        return result


class DiscoveryConnector:
    """Discovers case study URLs from a source using multiple methods."""

    def __init__(self, source_name: str, config: dict):
        self.name = source_name
        self.config = config
        self.root = config.get("root_domain", "")
        self.landings = config.get("known_landings", [])
        self.terms = config.get("discovery_terms", [])
        self.patterns = config.get("url_patterns", [])
        self.method = config.get("method", "requests")
        self.rate_limit = config.get("rate_limit", 1.0)
        self.validator = URLValidator()
        self.found_urls: list[dict] = []

    def discover_all(self, pilot: bool = False) -> list[dict]:
        max_per_source = 25 if pilot else 200
        self.found_urls = []

        self._try_landing_pages(max_per_source)
        if len([u for u in self.found_urls if u.get("valid")]) < 3:
            self._try_sitemap(max_per_source)
        if len([u for u in self.found_urls if u.get("valid")]) < 3:
            self._try_nav_search(max_per_source)

        return self.found_urls

    def _try_landing_pages(self, max_count: int):
        for landing in self.landings[:3]:
            result = self.validator.validate(landing)
            if result["valid"]:
                self.found_urls.append({"source": self.name, "landing": landing, "url": landing, "method": "known_landing", **result})
                self._extract_links(landing, max_count)
            time.sleep(self.rate_limit)

    def _try_sitemap(self, max_count: int):
        sitemap_urls = [
            urljoin(self.root, "/sitemap.xml"),
            urljoin(self.root, "/sitemap_index.xml"),
        ]
        for sm_url in sitemap_urls:
            try:
                import urllib.request
                req = urllib.request.Request(sm_url, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=10)
                body = resp.read().decode("utf-8", errors="replace")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body, "xml")
                for loc in soup.find_all("loc"):
                    u = loc.text.strip()
                    if any(p in u for p in self.patterns) and self._in_allowed_domain(u):
                        result = self.validator.validate(u)
                        self.found_urls.append({"source": self.name, "landing": "", "url": u, "method": "sitemap", **result})
                        if len([x for x in self.found_urls if x.get("valid")]) >= max_count:
                            return
            except: pass

    def _try_nav_search(self, max_count: int):
        """Try to find case study pages via navigation search on the root domain."""
        for landing in self.landings[:2]:
            try:
                import urllib.request
                req = urllib.request.Request(landing or self.root, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=10)
                html = resp.read().decode("utf-8", errors="replace")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.find_all("a", href=True):
                    u = urljoin(self.root, a["href"])
                    text = (a.get_text() or "").lower()
                    href = u.lower()
                    matched = any(p in href for p in self.patterns)
                    term_match = any(t.lower() in text for t in self.terms)
                    if matched and self._in_allowed_domain(u):
                        if u not in [x["url"] for x in self.found_urls]:
                            result = self.validator.validate(u)
                            self.found_urls.append({"source": self.name, "landing": landing, "url": u, "method": "nav_search" if term_match else "nav_match", **result})
                            if len([x for x in self.found_urls if x.get("valid")]) >= max_count:
                                return
                    time.sleep(self.rate_limit)
            except: pass

    def _extract_links(self, page_url: str, max_count: int):
        """Extract case-study-like links from a landing page."""
        try:
            import urllib.request
            req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode("utf-8", errors="replace")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                u = urljoin(page_url, href)
                if any(p in u.lower() for p in self.patterns) and self._in_allowed_domain(u):
                    if u not in [x["url"] for x in self.found_urls]:
                        result = self.validator.validate(u)
                        self.found_urls.append({"source": self.name, "landing": page_url, "url": u, "method": "extracted", **result})
                        if len([x for x in self.found_urls if x.get("valid")]) >= max_count:
                            return
        except: pass

    def _in_allowed_domain(self, url: str) -> bool:
        domain = urlparse(url).netloc
        allowed = self.config.get("allow_domains", [])
        return any(d in domain for d in allowed) if allowed else True


def run_pilot():
    registry = SourceRegistry()
    all_results = {}
    for name in registry.list_sources():
        logger.info(f"\n--- {name} ---")
        connector = DiscoveryConnector(name, registry.get(name))
        urls = connector.discover_all(pilot=True)
        valid = [u for u in urls if u.get("valid")]
        all_results[name] = {"found": len(urls), "valid": len(valid), "urls": valid[:5] if valid else []}
        logger.info(f"  Found: {len(urls)}, Valid: {len(valid)}")
        for u in valid[:5]:
            logger.info(f"    ✅ {u['url'][:80]}")

    # Report
    print("\n" + "=" * 80)
    print("DISCOVERY PILOT RESULTS")
    print("=" * 80)
    for name, r in sorted(all_results.items()):
        print(f"  {name:<20} found={r['found']:<3} valid={r['valid']:<3}")
    total_found = sum(r["found"] for r in all_results.values())
    total_valid = sum(r["valid"] for r in all_results.values())
    print(f"\n  Total found: {total_found}")
    print(f"  Total valid: {total_valid}")
    print("=" * 80)


def run_discover(args):
    registry = SourceRegistry()
    sources = [args.source] if args.source else registry.list_sources()
    all_results = {}
    for name in sources:
        config = registry.get(name)
        if not config:
            logger.warning(f"  Unknown source: {name}")
            continue
        logger.info(f"Discovering {name}...")
        connector = DiscoveryConnector(name, config)
        urls = connector.discover_all(pilot=args.pilot)
        valid = [u for u in urls if u.get("valid")]
        all_results[name] = {"found": len(urls), "valid": len(valid), "urls": [u["url"] for u in valid]}
        logger.info(f"  {name}: {len(valid)} valid URLs")
        time.sleep(1)
    return all_results


def run_report():
    """Report on all discovered URLs from cache."""
    cache_dir = CACHE_DIR / "url_validation"
    if not cache_dir.exists():
        logger.info("No cached validation data. Run --discover first.")
        return
    files = list(cache_dir.glob("*.json"))
    valid = 0
    invalid = 0
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
            if d.get("valid"):
                valid += 1
            else:
                invalid += 1
    logger.info(f"Validated URLs: {len(files)} (valid: {valid}, invalid: {invalid})")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--source", help="Specific source to discover")
    parser.add_argument("--output", default=str(REGISTRY_DIR / "discovered_urls.json"))
    args = parser.parse_args()

    if args.pilot:
        run_pilot()
    elif args.discover:
        results = run_discover(args)
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_path}")
    elif args.report:
        run_report()
    else:
        parser.print_help()
