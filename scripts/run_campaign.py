#!/usr/bin/env python3
"""
Evidence campaign runner.
Pipeline: Seed → Download PDF/HTML → Parse text → Save Document → LLM Extract → Evidence Graph

Usage:
  ./venv/bin/python3 scripts/run_campaign.py --campaign us_gao
  ./venv/bin/python3 scripts/run_campaign.py --campaign all
  ./venv/bin/python3 scripts/run_campaign.py --campaign oecd --dry-run
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compass_collector.database import get_session
from compass_collector.models.document import Document


CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "compass_collector/config/evidence_seeds.yaml",
)

USER_AGENT = "Mozilla/5.0 (compatible; CompassResearchBot/1.0; +http://compass.ai; research@compass.ai)"


def load_seeds():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_campaign(name: str, seeds: dict) -> dict | None:
    campaigns = seeds.get("campaigns", {})
    if name == "all":
        return campaigns
    if name in campaigns:
        return {name: campaigns[name]}
    return None


def download(url: str, timeout: int = 30) -> tuple[bytes | None, str, str]:
    """Download URL content. Returns (content, content_type, filename)."""
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, timeout=timeout, headers=headers, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "").lower()
        content = r.content
        # Extract filename
        filename = url.rstrip("/").split("/")[-1] or "index.html"
        if "?" in filename:
            filename = filename.split("?")[0]
        return content, content_type, filename
    except Exception as e:
        print(f"    ERROR downloading: {e}")
        return None, "", ""


def extract_text_html(content: bytes) -> str:
    """Extract text from HTML content."""
    soup = BeautifulSoup(content, "html.parser")
    # Remove script, style, nav, footer elements
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text


def extract_text_pdf(content: bytes) -> str:
    """Extract text from PDF content using pypdf."""
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(content))
    text_parts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            text_parts.append(t)
    return "\n\n".join(text_parts)


def process_url(url: str, title: str, description: str, provenance: str, dry_run: bool = False) -> bool:
    """Download, parse, save to Document table. Returns True if saved."""
    print(f"  Processing: {title[:70]}")

    if dry_run:
        print(f"    URL: {url}")
        print(f"    (dry-run, skipped)")
        return False

    # Check if already exists
    session = get_session()
    existing = session.query(Document).filter(Document.url == url).first()
    if existing and existing.cleaned_text and len(existing.cleaned_text) > 500:
        print(f"    ALREADY EXISTS ({len(existing.cleaned_text)} chars)")
        session.close()
        return False
    session.close()

    # Download
    content, content_type, filename = download(url)
    if not content:
        print(f"    FAILED: download returned empty")
        return False

    is_pdf = "pdf" in content_type or filename.endswith(".pdf") or url.endswith(".pdf")
    is_html = "html" in content_type or filename.endswith(".html") or filename.endswith(".htm") or not is_pdf

    # Parse
    if is_pdf:
        text = extract_text_pdf(content)
        parser = "pypdf"
    else:
        text = extract_text_html(content)
        parser = "bs4"

    if len(text) < 200:
        print(f"    SKIP: too short ({len(text)} chars)")
        return False

    # Save
    session = get_session()
    try:
        existing = session.query(Document).filter(Document.url == url).first()
        if existing:
            existing.cleaned_text = text
            existing.content_hash = hashlib.md5(text.encode()).hexdigest()[:32]
        else:
            import uuid
            doc = Document(
                id=str(uuid.uuid4()),
                url=url,
                title=title[:500],
                cleaned_text=text,
                content_hash=hashlib.md5(text.encode()).hexdigest()[:32],
                crawl_status="completed",
                parser_version=parser,
                created_at=datetime.now(timezone.utc),
            )
            session.add(doc)
        session.commit()
        print(f"    SAVED ({len(text)} chars, {parser})")
        return True
    except Exception as e:
        session.rollback()
        print(f"    ERROR saving: {e}")
        return False
    finally:
        session.close()


def run_campaign(name: str, campaign: dict, dry_run: bool = False):
    """Run a single campaign."""
    print(f"\n{'='*60}")
    print(f"Campaign: {campaign.get('name', name)}")
    print(f"Provenance: {campaign.get('provenance', 'unknown')}")
    print(f"{'='*60}")

    urls = campaign.get("urls", [])
    if not urls:
        print("  No URLs defined (API-based or manual seed)")
        return

    saved = 0
    total = len(urls)

    for entry in urls:
        if isinstance(entry, str):
            entry = {"url": entry, "title": entry, "description": ""}
        ok = process_url(
            entry["url"],
            entry.get("title", ""),
            entry.get("description", ""),
            campaign.get("provenance", "unknown"),
            dry_run=dry_run,
        )
        if ok:
            saved += 1
        time.sleep(1.0)  # Rate limit

    print(f"\n  Result: {saved}/{total} new documents saved")


def run_extraction():
    """Run batch extraction on unprocessed documents."""
    print("\n  Running LLM extraction on new documents...")
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/batch_extract.py"],
        capture_output=True, text=True, timeout=600,
    )
    for line in result.stdout.split("\n")[-10:]:
        if line.strip():
            print(f"    {line}")


def main():
    parser = argparse.ArgumentParser(description="Run evidence campaigns")
    parser.add_argument("--campaign", "-c", default="all",
                        help="Campaign name or 'all'")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be downloaded without saving")
    parser.add_argument("--extract", "-e", action="store_true",
                        help="Run LLM extraction after seeding")
    args = parser.parse_args()

    seeds = load_seeds()
    campaigns = get_campaign(args.campaign, seeds)

    if not campaigns:
        print(f"Campaign '{args.campaign}' not found.")
        print(f"Available: {', '.join(seeds.get('campaigns', {}).keys())}")
        sys.exit(1)

    for name, campaign in campaigns.items():
        run_campaign(name, campaign, dry_run=args.dry_run)

    if args.extract:
        run_extraction()


if __name__ == "__main__":
    main()
