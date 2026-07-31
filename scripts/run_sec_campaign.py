#!/usr/bin/env python3
"""
SEC EDGAR evidence campaign.
Searches EDGAR full-text index for quantified operational transformation outcomes,
then downloads, parses, and stores the filings for LLM extraction.

Usage:
  ./venv/bin/python3 scripts/run_sec_campaign.py --search "supply chain automation reduced costs" --limit 20
  ./venv/bin/python3 scripts/run_sec_campaign.py --company walmart --limit 5
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compass_collector.database import get_session
from compass_collector.models.document import Document

HEADERS = {"User-Agent": "Compass Research research@compass.ai"}

SEARCH_QUERIES = [
    "supply chain automation reduced costs",
    "ERP implementation cost savings",
    "claims processing time reduced from",
    "customer service automation reduced handle time",
    "back-office automation annual savings",
    "robotic process automation savings",
    "AI implementation reduced processing time",
    "digital transformation productivity improvement",
    "automated order processing reduced errors",
    "data center consolidation cost savings",
    "shared services implementation savings",
    "workflow automation reduced manual",
]


def edgar_search(query: str, forms: str = "10-K,10-Q,8-K", limit: int = 50):
    """Search EDGAR full-text index."""
    url = f"https://efts.sec.gov/LATEST/search-index?q={quote(query)}&forms={forms}"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    data = r.json()
    hits = data.get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src = h.get("_source", {})
        full_id = h.get("_id", "")
        display = src.get("display_names", [""])
        company = re.search(r"\((CIK\s+)?(\d+)\)", display[0]) if display else None
        cik = company.group(2) if company else ""
        # Parse _id like "0001837240-22-000049:sym-20220924.htm"
        if ":" in full_id:
            accession, filename = full_id.split(":", 1)
            results.append({
                "accession": accession,
                "filename": filename,
                "cik": cik,
                "date": src.get("file_date", ""),
                "name": display[0].split("  (CIK")[0] if display else "",
            })
    return results


def edgar_url(cik: str, accession: str, filename: str) -> str:
    """Construct the EDGAR document URL."""
    acc_no_dashes = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dashes}/{filename}"


def extract_text(content: bytes, content_type: str, filename: str) -> str:
    """Extract text from HTML/XML/PDF filing."""
    if "pdf" in content_type or filename.endswith(".pdf"):
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(content))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def save_document(url: str, title: str, text: str, parser: str) -> bool:
    """Save document to DB, skip if already present."""
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
                title=title[:500],
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
    parser = argparse.ArgumentParser(description="SEC EDGAR evidence campaign")
    parser.add_argument("--search", "-s", action="store_true", help="Run all default searches")
    parser.add_argument("--query", "-q", help="Custom search query")
    parser.add_argument("--company", "-c", help="Search filings for a specific company")
    parser.add_argument("--limit", "-l", type=int, default=50, help="Max filings per query")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()

    queries = []
    if args.query:
        queries.append(args.query)
    if args.company:
        queries.append(f"{args.company} automation OR transformation OR ERP")
    if args.search or not (args.query or args.company):
        queries.extend(SEARCH_QUERIES)

    # Dedupe
    results_by_key = {}
    for q in queries:
        print(f"\n=== Searching: {q} ===")
        try:
            results = edgar_search(q, limit=args.limit)
            print(f"  Found {len(results)} hits")
            for res in results:
                if not res["cik"]:
                    continue
                key = (res["cik"], res["accession"])
                if key not in results_by_key:
                    results_by_key[key] = res
        except Exception as e:
            print(f"  Search error: {e}")
        time.sleep(1.0)

    filings = list(results_by_key.values())
    print(f"\n{'-'*60}")
    print(f"Unique filings: {len(filings)}")

    if args.dry_run:
        for f in filings[:20]:
            url = edgar_url(f["cik"], f["accession"], f["filename"])
            print(f"  {f['date']} {f['name'][:40]} :: {url}")
        return

    # Download each filing
    saved = 0
    for i, f in enumerate(filings, 1):
        url = edgar_url(f["cik"], f["accession"], f["filename"])
        print(f"  [{i}/{len(filings)}] {f['name'][:40]}...", end=" ")
        try:
            r = requests.get(url, timeout=30, headers=HEADERS)
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            content_type = r.headers.get("Content-Type", "")
            text = extract_text(r.content, content_type, f["filename"])
            if len(text) < 2000:
                print(f"short ({len(text)} chars)")
                continue
            ok = save_document(url, f"{f['name']} ({f['date']} {f['filename']})", text, "bs4")
            if ok:
                saved += 1
                print(f"saved ({len(text)} chars)")
            else:
                print("exists/skip")
        except Exception as e:
            print(f"error: {e}")
        time.sleep(0.5)

    print(f"\nSaved: {saved} new SEC documents")


if __name__ == "__main__":
    main()
