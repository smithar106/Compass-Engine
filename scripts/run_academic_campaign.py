#!/usr/bin/env python3
"""
Academic implementation studies campaign.
Targets implementation outcome studies — not AI theory.
Sources: PubMed, Nature, Springer.

Usage:
  ./venv/bin/python3 scripts/run_academic_campaign.py --source pubmed --limit 20
  ./venv/bin/python3 scripts/run_academic_campaign.py --source nature --limit 10
"""

import argparse
import hashlib
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compass_collector.database import get_session
from compass_collector.models.document import Document

HEADERS = {"User-Agent": "Mozilla/5.0 (research; +http://compass.ai)"}

PUBMED_QUERIES = [
    "electronic health record implementation workflow efficiency",
    "ERP implementation outcomes hospital",
    "AI implementation healthcare outcomes",
    "robotic process automation implementation",
    "digital health implementation evaluation",
    "clinical decision support implementation outcomes",
]

NATURE_QUERIES = [
    "ERP implementation case study",
    "digital transformation implementation outcomes",
    "enterprise automation implementation",
    "workflow automation evaluation",
    "business process management implementation",
]


def pubmed_search(query: str, limit: int = 20):
    """Search PubMed and extract article metadata + abstracts."""
    url = f"https://pubmed.ncbi.nlm.nih.gov/?term={query.replace(' ', '+')}"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    for article in soup.select("article.full-docsum"):
        title_el = article.select_one(".docsum-title")
        if not title_el:
            continue
        href = title_el.get("href", "")
        pmid = href.strip("/").split("/")[-1] if href else ""
        title = title_el.get_text(strip=True)
        journal = article.select_one(".docsum-journal-citation")
        results.append({
            "pmid": pmid,
            "title": title,
            "journal": journal.get_text(strip=True) if journal else "",
        })
    return results[:limit]


def pubmed_abstract(pmid: str) -> str:
    """Fetch the abstract for a PubMed article."""
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    abstract_el = soup.select_one(".abstract-content")
    title = soup.select_one("h1.heading-title")
    text_parts = []
    if title:
        text_parts.append(title.get_text(strip=True))
    if abstract_el:
        text_parts.append(abstract_el.get_text(separator="\n", strip=True))
    return "\n\n".join(text_parts)


def nature_search(query: str, limit: int = 10):
    """Search Nature and extract article links."""
    url = f"https://www.nature.com/search?q={query.replace(' ', '+')}&journal=npjdigitalmed,npjinfo"
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    for a in soup.select("h3[data-test='result-title'] a, a[data-track-action='view article']"):
        href = a.get("href", "")
        if href.startswith("/articles/") or href.startswith("/s"):
            full = f"https://www.nature.com{href}" if href.startswith("/") else href
            title = a.get_text(strip=True)
            if title:
                results.append({"url": full, "title": title})
    return results[:limit]


def save_document(url: str, title: str, text: str) -> bool:
    session = get_session()
    existing = session.query(Document).filter(Document.url == url).first()
    if existing and existing.cleaned_text and len(existing.cleaned_text) > 500:
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
                parser_version="bs4",
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


def fetch_nature(url: str) -> str:
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    main = soup.select_one("article") or soup
    return main.get_text(separator="\n", strip=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", "-s", choices=["pubmed", "nature", "all"], default="all")
    parser.add_argument("--limit", "-l", type=int, default=15)
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()

    if args.source in ("pubmed", "all"):
        print("=== PUBMED ===")
        for q in PUBMED_QUERIES:
            print(f"\n  Query: {q}")
            try:
                articles = pubmed_search(q, limit=args.limit)
                print(f"    {len(articles)} articles found")
                for a in articles[:args.limit]:
                    print(f"      [{a['pmid']}] {a['title'][:70]}")
                    if args.dry_run:
                        continue
                    abstract = pubmed_abstract(a["pmid"])
                    if len(abstract) > 200:
                        url = f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
                        ok = save_document(url, a["title"], abstract)
                        if ok:
                            print(f"        saved ({len(abstract)} chars)")
                    time.sleep(0.5)
            except Exception as e:
                print(f"    error: {e}")
            time.sleep(1.0)

    if args.source in ("nature", "all"):
        print("\n=== NATURE ===")
        for q in NATURE_QUERIES:
            print(f"\n  Query: {q}")
            try:
                articles = nature_search(q, limit=args.limit)
                print(f"    {len(articles)} articles found")
                for a in articles:
                    print(f"      {a['title'][:70]}")
                    if args.dry_run:
                        continue
                    try:
                        text = fetch_nature(a["url"])
                        if len(text) > 1000:
                            ok = save_document(a["url"], a["title"], text)
                            if ok:
                                print(f"        saved ({len(text)} chars)")
                    except Exception as e:
                        print(f"        error: {e}")
                    time.sleep(1.0)
            except Exception as e:
                print(f"    error: {e}")
            time.sleep(1.0)


if __name__ == "__main__":
    main()
