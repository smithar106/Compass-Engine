#!/usr/bin/env python3
"""Fetch full article text for all documents and save to cleaned_text."""

import sys, os, uuid, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup
from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import QualityFlag

init_db()
session = get_session()

docs = session.query(Document).filter(
    Document.url.startswith("http"),
    Document.cleaned_text == ""
).all()

total = len(docs)
print(f"Fetching text for {total} documents...")

fetched = 0
errors = 0
for i, doc in enumerate(docs):
    try:
        resp = requests.get(
            doc.url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CompassCollector/1.0)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        doc.cleaned_text = text[:10000]
        fetched += 1

        if i % 100 == 0 and i > 0:
            session.commit()
            print(f"  {i}/{total} — {fetched} fetched, {errors} errors")
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error {i}: {str(e)[:80]}")

session.commit()
print(f"\nDone! {fetched} documents fetched, {errors} errors.")
print(f"Documents with text: {session.query(Document).filter(Document.cleaned_text != '').count()}")
session.close()
