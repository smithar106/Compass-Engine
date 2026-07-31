#!/usr/bin/env python3
"""Customer Implementation Library Campaign.

Targets vendor customer-story pages for implementation-rich evidence:
  * implementation partner
  * rollout strategy
  * change management
  * lessons learned
  * organizational context

Sources: AWS, Google Cloud, Microsoft, Snowflake, Databricks, Salesforce,
ServiceNow, UiPath, Workday, Atlassian, SAP, Oracle.

Usage:
  ./venv/bin/python3 scripts/run_implementation_campaign.py --source aws --limit 20
  ./venv/bin/python3 scripts/run_implementation_campaign.py --all --limit 10
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import get_session
from compass_collector.models.document import Document

SOURCES = {
    "aws": {
        "name": "AWS Customer Stories",
        "list_url": "https://aws.amazon.com/solutions/case-studies/",
        "story_selector": 'a[href*="/solutions/case-studies/"]',
        "story_prefix": "https://aws.amazon.com",
    },
    "gcp": {
        "name": "Google Cloud Customers",
        "list_url": "https://cloud.google.com/customers/",
        "story_selector": 'a[href*="/customers/"]',
        "story_prefix": "https://cloud.google.com",
    },
    "msft": {
        "name": "Microsoft Customer Stories",
        "list_url": "https://customers.microsoft.com/en-us/search?sq=&ff=story_product_categories%26%3EAzure&p=0&so=story_publish_date%20desc",
        "story_selector": 'a[href*="/en-us/story/"]',
        "story_prefix": "https://customers.microsoft.com",
    },
    "snowflake": {
        "name": "Snowflake Customer Stories",
        "list_url": "https://www.snowflake.com/en/customers/",
        "story_selector": 'a[href*="/customers/"]',
        "story_prefix": "https://www.snowflake.com",
    },
    "databricks": {
        "name": "Databricks Customer Stories",
        "list_url": "https://www.databricks.com/customers",
        "story_selector": 'a[href*="/customers/"]',
        "story_prefix": "https://www.databricks.com",
    },
    "salesforce": {
        "name": "Salesforce Customer Success",
        "list_url": "https://www.salesforce.com/customer-success-stories/",
        "story_selector": 'a[href*="/customer-success-stories/"]',
        "story_prefix": "https://www.salesforce.com",
    },
    "servicenow": {
        "name": "ServiceNow Customer Stories",
        "list_url": "https://www.servicenow.com/success.html",
        "story_selector": 'a[href*="/success/"]',
        "story_prefix": "https://www.servicenow.com",
    },
    "uipath": {
        "name": "UiPath Automation Stories",
        "list_url": "https://www.uipath.com/resources/automation-case-studies",
        "story_selector": 'a[href*="/resources/automation-case-studies/"]',
        "story_prefix": "https://www.uipath.com",
    },
    "sap": {
        "name": "SAP Customer Stories",
        "list_url": "https://www.sap.com/about/customer-stories.html",
        "story_selector": 'a[href*="/customer-stories/"]',
        "story_prefix": "https://www.sap.com",
    },
    "oracle": {
        "name": "Oracle Customers",
        "list_url": "https://www.oracle.com/customers/",
        "story_selector": 'a[href*="/customers/"]',
        "story_prefix": "https://www.oracle.com",
    },
    "accenture": {
        "name": "Accenture Case Studies",
        "list_url": "https://www.accenture.com/us-en/case-studies",
        "story_selector": 'a[href*="/case-studies/"]',
        "story_prefix": "https://www.accenture.com",
    },
    "deloitte": {
        "name": "Deloitte Client Stories",
        "list_url": "https://www.deloitte.com/global/en/about/people/case-studies.html",
        "story_selector": 'a[href*="/case-studies/"]',
        "story_prefix": "https://www.deloitte.com",
    },
    "mckinsey": {
        "name": "McKinsey Client Case Studies",
        "list_url": "https://www.mckinsey.com/about-us/case-studies",
        "story_selector": 'a[href*="/case-studies/"]',
        "story_prefix": "https://www.mckinsey.com",
    },
}


def fetch_url(url: str, use_wayback: bool = False) -> tuple[str, str]:
    """Fetch a URL. Returns (html, source_method)."""
    headers = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    ]
    for ua in headers:
        try:
            r = subprocess.run(
                ["curl", "-sL", "-A", ua, "--max-time", "30", url],
                capture_output=True, text=True, timeout=35,
            )
            if len(r.stdout) > 500 and r.returncode == 0:
                return r.stdout, "direct"
        except Exception:
            pass
        time.sleep(1)
    if use_wayback:
        try:
            wb_url = f"https://web.archive.org/web/2025/{url}"
            r = subprocess.run(
                ["curl", "-sL", "-A", headers[0], "--max-time", "30", wb_url],
                capture_output=True, text=True, timeout=35,
            )
            if len(r.stdout) > 500:
                return r.stdout, "wayback"
        except Exception:
            pass
    return "", "failed"


def parse_links(html: str, selector: str, prefix: str, limit: int) -> list[str]:
    """Extract story links from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.select(selector):
        href = a.get("href", "")
        if not href or href.startswith("#"):
            continue
        if href.startswith("/"):
            href = prefix.rstrip("/") + href
        elif not href.startswith("http"):
            href = prefix.rstrip("/") + "/" + href
        links.add(href)
    return sorted(links)[:limit]


def save_document(url: str, html: str, title: str = "") -> str:
    """Save fetched page as Document. Returns doc_id or empty string."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)[:500000]
    if len(text) < 300:
        return ""
    if not title:
        t = soup.title
        title = str(t.string)[:500] if t and t.string else url.split("/")[-1]
    did = str(uuid.uuid4())
    session = get_session()
    try:
        doc = Document(
            id=did, source_registry_id=f"impl-{did[:6]}", url=url,
            title=str(title)[:500], document_type="implementation_story",
            cleaned_text=text,
            content_hash=hashlib.sha256(html.encode()).hexdigest()[:32],
            crawl_status="fetched", retrieved_at=datetime.now(timezone.utc),
        )
        session.add(doc)
        session.commit()
        print(f"    saved doc: {did[:8]}... ({len(text):,} chars)")
        return did
    except Exception as e:
        session.rollback()
        print(f"    save error: {e}")
        return ""
    finally:
        session.close()


def fetch_story(url: str, title: str) -> str:
    """Fetch a single story page. Returns doc_id or empty string."""
    session = get_session()
    existing = session.query(Document).filter(Document.url == url).first()
    session.close()
    if existing:
        print(f"    already in DB: {url[:70]}")
        return existing.id

    html, method = fetch_url(url, use_wayback=True)
    if not html:
        print(f"    fetch failed: {url[:70]}")
        return ""
    print(f"    fetched ({method}, {len(html):,} chars): {url[:70]}")
    return save_document(url, html, title)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", "-s", choices=list(SOURCES.keys()) + ["all"], default="gcp")
    parser.add_argument("--limit", "-l", type=int, default=15, help="Max stories to fetch per source")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    sources_to_run = list(SOURCES.keys()) if args.all or args.source == "all" else [args.source]

    for src_key in sources_to_run:
        src = SOURCES[src_key]
        print(f"\n{'='*60}")
        print(f"Campaign: {src['name']} ({src_key})")
        print(f"Listing: {src['list_url']}")
        print(f"{'='*60}")

        html, method = fetch_url(src["list_url"], use_wayback=True)
        if not html:
            print(f"  listing page fetch failed")
            continue
        print(f"  listing fetched ({method}, {len(html):,} chars)")

        links = parse_links(html, src["story_selector"], src["story_prefix"], args.limit)
        print(f"  found {len(links)} story links")

        saved = 0
        for link in links:
            title = link.split("/")[-1].replace("-", " ").replace(".html", "").title()
            did = fetch_story(link, title)
            if did:
                saved += 1
            time.sleep(1)
        print(f"  saved {saved}/{len(links)} stories for {src_key}")

    # Final stats
    print(f"\n{'='*60}")
    session = get_session()
    from sqlalchemy import func
    total = session.query(func.count(Document.id)).scalar()
    impl = session.query(func.count(Document.id)).filter(
        Document.document_type == "implementation_story"
    ).scalar()
    session.close()
    print(f"Documents: {total:,} total, {impl:,} implementation stories")
    print(f"Next: run provenance extraction on new docs")


if __name__ == "__main__":
    main()
