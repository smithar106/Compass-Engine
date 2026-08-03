"""Acquisition strategies for Source Libraries.

A Source Library is collected via a chosen acquisition strategy — FetchFox
browser automation, the existing static crawler, OpenCLI browser, direct API,
or RSS. The Campaign Planner selects the strategy per library (preferred /
fallback) and learns which performs best over time (accepted records, cost per
accepted). FetchFox is reserved for JS-heavy / interactive / paginated customer
story libraries — never broad web search.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("compass_agent.acquisition")

# Implementation-evidence extraction template used by FetchFox. Each page in a
# customer-story library yields one item; the second .extract() follows the
# detail-page URL to pull deep implementation fields.
FETCHFOX_SCRIPT_TEMPLATE = """const {{ fox }} = require('fetchfox');
(async () => {{
  const workflow = await fox
    .init('{entry}')
    .extract({{
      url: 'URL of the individual case study / customer story page',
      organization_name: 'company or organization name',
      organization_industry: 'industry (e.g. financial_services, healthcare, retail_consumer, technology, manufacturing)',
      workflow: 'specific operational workflow described',
      intervention_title: 'what was implemented',
      intervention_category: 'Workflow_Automation | AI | Software | Process_Redesign | Staffing | Hybrid'
    }})
    .extract({{
      evidence_tier: 'gold | silver | bronze | rejected',
      rollout_strategy: 'how it was rolled out',
      success_criteria: 'validation gates or success measures',
      lessons_learned: 'lessons learned',
      outcomes: 'measured outcomes with numbers (e.g. reduced cycle time 40%)'
    }})
    .limit({limit})
    .plan();
  const results = await workflow.run();
  console.log(JSON.stringify(results.items));
}})().catch(e => {{ console.error('FETCHFOX_ERROR: ' + e); process.exit(1); }});
"""


class AcquisitionStrategy:
    """Protocol: a way to collect evidence from a Source Library."""

    name = "static"

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        """Return a list of raw implementation candidates: dicts with
        organization/implementation fields (FetchFox items) OR
        {url, title} page candidates for downstream extraction."""
        raise NotImplementedError


class StaticAcquisition(AcquisitionStrategy):
    """The existing crawler: discover entry URLs, follow case-study links, and
    return un-processed page candidates. Pages are claimed in the store so they
    are never re-crawled across runs."""

    name = "static"

    def __init__(self, fetcher, store=None) -> None:
        self.fetcher = fetcher
        self.store = store

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        candidates: list[dict] = []
        entries = library.get("entry_urls", [])[:3]
        for entry in entries:
            candidates.append({"url": entry, "title": library["name"]})
            links = self.fetcher.fetch_links(entry) if hasattr(self.fetcher, "fetch_links") else []
            for link in links[: max_pages * 3]:
                candidates.append(link)

        if self.store is None:
            return candidates[: max(max_pages, 10)]

        # persist + return only pages not yet processed
        out = []
        for c in candidates:
            self.store.claim_library_page(c["url"], library["id"], c.get("title", ""))
            if self.store.library_page_status(c["url"]) == "discovered":
                out.append(c)
            if len(out) >= max_pages:
                break
        return out


class FetchFoxAcquisition(AcquisitionStrategy):
    """Browser automation via the FetchFox npm package (Node + Playwright).

    Runs a generated workflow against a library's entry URL, extracts
    implementation evidence directly from each customer-story page (following
    detail links), and returns structured items ready for validation + ingest.
    Requires: node, the fetchfox npm package, playwright browsers, and an AI
    provider key (OPENAI_API_KEY or FETCHFOX_AI). Graceful no-op otherwise.
    """

    name = "fetchfox"

    def __init__(self, tools_dir: str = "", ai: str = "") -> None:
        self.tools_dir = Path(tools_dir or os.environ.get("AGENT_TOOLS_DIR", "/app/tools"))
        self.ai = ai or os.environ.get("FETCHFOX_AI", "openai:gpt-4o-mini")
        self.ai_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("FETCHFOX_API_KEY", "")

    def _node_bin(self) -> Optional[str]:
        node = shutil.which("node")
        if node:
            return node
        candidate = self.tools_dir / "node" / "bin" / "node"
        return str(candidate) if candidate.exists() else None

    def _ensure_package(self, node: str) -> bool:
        pkg = self.tools_dir / "fetchfox" / "node_modules" / "fetchfox"
        if pkg.exists():
            return True
        try:
            env = dict(os.environ)
            env["PATH"] = f"{self.tools_dir / 'node' / 'bin'}:{env.get('PATH', '')}"
            subprocess.run(
                [node, str(self.tools_dir / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
                 "install", "--prefix", str(self.tools_dir / "fetchfox"), "fetchfox"],
                capture_output=True, text=True, timeout=300, env=env,
            )
            return pkg.exists()
        except Exception as exc:
            log.warning("fetchfox install failed: %s", exc)
            return False

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        if not self.ai_key:
            log.warning("FetchFox skipped for %s: no AI provider key (OPENAI_API_KEY)", library.get("id"))
            return []
        node = self._node_bin()
        if not node:
            log.warning("FetchFox skipped for %s: no node", library.get("id"))
            return []
        if not self._ensure_package(node):
            return []
        entry = (library.get("entry_urls") or [""])[0]
        if not entry:
            return []
        script = FETCHFOX_SCRIPT_TEMPLATE.format(entry=entry, limit=max_pages)
        script_path = self.tools_dir / "fetchfox" / "crawl.js"
        try:
            script_path.write_text(script)
            env = dict(os.environ)
            env["PATH"] = f"{self.tools_dir / 'node' / 'bin'}:{env.get('PATH', '')}"
            env["OPENAI_API_KEY"] = self.ai_key
            env["FETCHFOX_AI"] = self.ai
            result = subprocess.run(
                [node, str(script_path)],
                capture_output=True, text=True, timeout=240, env=env,
            )
            if result.returncode != 0:
                log.warning("fetchfox run failed for %s: %s", library.get("id"), (result.stderr or "")[-300:])
                return []
            items = json.loads(result.stdout)
            if not isinstance(items, list):
                return []
            return [i for i in items if isinstance(i, dict)]
        except Exception as exc:
            log.warning("fetchfox crawl error for %s: %s", library.get("id"), exc)
            return []


class OpenCLIAcquisition(AcquisitionStrategy):
    """OpenCLI browser acquisition — used when a browser bridge profile is
    connected. Without one it returns nothing (graceful)."""

    name = "opencli_browser"

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        # Requires a connected Chrome profile (opencli browser bridge). Not
        # available headlessly; return nothing so the planner falls back.
        return []


class RSSAcquisition(AcquisitionStrategy):
    """Collect via an RSS feed (e.g. engineering blogs, government blogs)."""

    name = "rss"

    def __init__(self, fetcher, store=None) -> None:
        self.fetcher = fetcher
        self.store = store

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        feed_url = (library.get("entry_urls") or [""])[0]
        if not feed_url:
            return []
        try:
            import feedparser

            feed = feedparser.parse(feed_url)
            out = []
            for entry in feed.entries[:max_pages * 3]:
                link = entry.get("link", "")
                if not link:
                    continue
                if self.store is not None:
                    self.store.claim_library_page(link, library["id"], entry.get("title", ""))
                    if self.store.library_page_status(link) != "discovered":
                        continue
                out.append({"url": link, "title": entry.get("title", "")})
                if len(out) >= max_pages:
                    break
            return out
        except Exception as exc:
            log.warning("rss crawl failed for %s: %s", library.get("id"), exc)
            return []


class DirectAPIAcquisition(AcquisitionStrategy):
    """Collect via a direct JSON/API endpoint. Configure the library with a
    ``api_url`` entry; each list item should carry implementation-ish fields."""

    name = "direct_api"

    def crawl(self, library: dict, max_pages: int) -> list[dict]:
        api_url = (library.get("api_urls") or library.get("entry_urls") or [""])[0]
        if not api_url:
            return []
        try:
            import httpx

            resp = httpx.get(api_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", data.get("results", []))
            if not isinstance(items, list):
                return []
            out = []
            for item in items[:max_pages]:
                if isinstance(item, dict) and item.get("organization_name"):
                    out.append(item)
            return out
        except Exception as exc:
            log.warning("direct_api crawl failed for %s: %s", library.get("id"), exc)
            return []


STRATEGIES: dict[str, type] = {
    "static": StaticAcquisition,
    "fetchfox": FetchFoxAcquisition,
    "opencli_browser": OpenCLIAcquisition,
    "rss": RSSAcquisition,
    "direct_api": DirectAPIAcquisition,
}


def build_strategy(name: str, fetcher, store=None) -> Optional[AcquisitionStrategy]:
    if name == "static":
        return StaticAcquisition(fetcher, store)
    if name == "fetchfox":
        return FetchFoxAcquisition()
    if name == "opencli_browser":
        return OpenCLIAcquisition()
    if name == "rss":
        return RSSAcquisition(fetcher, store)
    if name == "direct_api":
        return DirectAPIAcquisition()
    return None


def pick_strategy(library: dict, store) -> str:
    """Choose the acquisition strategy name for a library, learning from
    performance. Uses the preferred strategy unless it has been tried repeatedly
    with zero acceptances and an un-tried fallback exists."""
    acquisition = library.get("acquisition") or {}
    preferred = acquisition.get("preferred", "static")
    fallback = acquisition.get("fallback", "static")
    stats = library.get("acquisition_stats") or {}
    pref_stats = stats.get(preferred) or {}

    if (pref_stats.get("runs", 0) >= 2 and pref_stats.get("accepted", 0) == 0
            and fallback and fallback != preferred and not stats.get(fallback)):
        chosen = fallback
    else:
        chosen = preferred
    log.info("library %s acquisition strategy: %s", library.get("id"), chosen)
    return chosen


def record_acquisition_result(store, library_id: str, strategy: str, accepted: int, cost: float, pages: int) -> None:
    libs = store.list_libraries()
    lib = next((l for l in libs if l["id"] == library_id), None)
    if lib is None:
        return
    stats = lib.get("acquisition_stats") or {}
    entry = stats.get(strategy) or {"runs": 0, "accepted": 0, "cost": 0.0, "pages": 0}
    entry["runs"] += 1
    entry["accepted"] += accepted
    entry["cost"] = round(entry.get("cost", 0.0) + cost, 6)
    entry["pages"] += pages
    stats[strategy] = entry
    store.update_library(library_id, acquisition_stats=json.dumps(stats))
