#!/usr/bin/env python3
"""Search-driven case study discovery.

Uses DuckDuckGo/Bing search to find case study libraries and specific
implementation case studies with quantified outcomes, then fetches and
stores the content for extraction.

Usage:
  ./venv/bin/python3 scripts/discover_via_search.py --queries "ERP implementation case study" --limit 100
  ./venv/bin/python3 scripts/discover_via_search.py --default  # runs curated query set
"""

import argparse
import hashlib
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compass_collector.database import get_session
from compass_collector.models.document import Document

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

DEFAULT_QUERIES = [
    # Case study libraries (high yield, many individual studies inside)
    "case study library implementation outcomes business",
    "digital transformation case study library ROI",
    "AI implementation case study library outcomes",
    "ERP implementation case study library",
    "supply chain automation case study library",
    "robotic process automation case study library",
    # Specific quantified outcomes
    "ERP implementation reduced processing time case study",
    "customer service automation reduced handle time case study",
    "back office automation annual savings case study",
    "claims processing automation reduced days case study",
    "supply chain digitalization savings case study",
    "AI chatbot customer support implementation results",
    # Academic implementation studies
    "digital transformation implementation evaluation study journal",
    "ERP implementation success case study journal",
    "workflow automation evaluation case study",
    "business process automation case study results quantified",
    # Consulting firm case studies
    "McKinsey digital transformation case study savings",
    "Accenture automation case study outcomes",
    "Deloitte ERP implementation case study results",
]


def ddg_search(query: str, max_results: int = 20) -> list[dict]:
    """DuckDuckGo HTML search with retry, decoding redirect URLs."""
    from urllib.parse import quote_plus
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20, headers=HEADERS)
            if r.status_code == 202 or len(r.text) < 2000:
                time.sleep(8 * (attempt + 1))
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for result in soup.find_all("div", class_="result")[:max_results]:
                title_tag = result.find("a", class_="result__a")
                snippet_tag = result.find("a", class_="result__snippet")
                if title_tag:
                    href = title_tag.get("href", "")
                    # Decode DDG redirect
                    if "uddg=" in href:
                        href = unquote(href.split("uddg=")[1].split("&")[0])
                    results.append({
                        "url": href,
                        "title": title_tag.get_text(strip=True),
                        "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
                    })
            return results
        except Exception as e:
            if attempt == 2:
                return []
            time.sleep(8 * (attempt + 1))
    return []


def is_useful(url: str, title: str, snippet: str) -> bool:
    """Filter out low-value URLs."""
    low_value = [
        "facebook.com", "twitter.com", "youtube.com", "instagram.com",
        "linkedin.com/feed", "amazon.com", "wikipedia.org/wiki/LinkedIn",
        ".pdf", "reddit.com", "quora.com",
    ]
    u = url.lower()
    for bad in low_value:
        if bad in u:
            return False
    # Require some signal
    text = (title + " " + snippet).lower()
    keywords = ["case study", "implementation", "outcome", "transformation", "automation",
                "erp", "rpa", "saved", "reduced", "improved", "roi", "results", "success"]
    return any(k in text for k in keywords)


def fetch_text(url: str) -> tuple[str | None, str]:
    """Fetch and extract text. Returns (text, parser)."""
    try:
        r = requests.get(url, timeout=25, headers=HEADERS, allow_redirects=True)
        if r.status_code != 200:
            return None, "error"
        ct = r.headers.get("Content-Type", "")
        if "pdf" in ct or url.endswith(".pdf"):
            from io import BytesIO
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(r.content))
            text = "\n\n".join((p.extract_text() or "") for p in reader.pages)
            return text, "pypdf"
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text, "bs4"
    except Exception:
        return None, "error"


def save_document(url: str, title: str, text: str, parser: str) -> bool:
    session = get_session()
    existing = session.query(Document).filter(Document.url == url).first()
    if existing and existing.cleaned_text and len(existing.cleaned_text) > 1000:
        session.close()
        return False
    try:
        if existing:
            existing.cleaned_text = text
            existing.content_hash = hashlib.md5(text.encode()).hexdigest()[:32]
        else:
            doc = Document(
                id=str(uuid.uuid4()),
                url=url,
                title=(title or url)[:500],
                cleaned_text=text,
                content_hash=hashlib.md5(text.encode()).hexdigest()[:32],
                crawl_status="completed",
                parser_version=parser,
                created_at=datetime.now(timezone.utc),
            )
            session.add(doc)
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", "-q", nargs="*", help="Custom queries")
    parser.add_argument("--default", "-d", action="store_true", help="Run curated query set")
    parser.add_argument("--limit", "-l", type=int, default=20, help="Results per query")
    parser.add_argument("--fetch-limit", type=int, default=100, help="Max URLs to fetch")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()

    queries = args.queries if args.queries else (DEFAULT_QUERIES if args.default else None)
    if not queries:
        queries = DEFAULT_QUERIES

    # Discover URLs
    all_urls = {}
    for q in queries:
        print(f"\n=== Searching: {q} ===")
        try:
            results = ddg_search(q, max_results=args.limit)
            for r in results:
                url = r["url"]
                if not url.startswith("http"):
                    continue
                if is_useful(url, r["title"], r["snippet"]):
                    if url not in all_urls:
                        all_urls[url] = (r["title"], r["snippet"])
            print(f"  {len(results)} results, {len(all_urls)} unique so far")
        except Exception as e:
            print(f"  error: {e}")
        time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Unique useful URLs: {len(all_urls)}")

    if args.dry_run:
        for i, (url, (title, snip)) in enumerate(sorted(all_urls.items(), key=lambda x: x[1][1], reverse=True)):
            if i >= args.fetch_limit:
                break
            print(f"  {title[:60]} :: {url[:80]}")
        return

    # Fetch each
    saved = 0
    fetched = 0
    for url, (title, snip) in sorted(all_urls.items(), key=lambda x: x[1][1], reverse=True):
        if fetched >= args.fetch_limit:
            break
        fetched += 1
        text, parser = fetch_text(url)
        if text and len(text) > 1000:
            if save_document(url, title, text, parser):
                saved += 1
                print(f"  [{fetched}/{args.fetch_limit}] ✅ {title[:50]} ({len(text)} chars)")
            else:
                print(f"  [{fetched}/{args.fetch_limit}] ⏭ {title[:50]} (exists)")
        else:
            print(f"  [{fetched}/{args.fetch_limit}] ❌ {title[:50]}")
        time.sleep(1.0)

    print(f"\nSaved: {saved} new documents from {len(all_urls)} discovered URLs")


if __name__ == "__main__":
    main()
