#!/usr/bin/env python3
"""Fetch full article text for all intervention records and re-extract fields."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import time
import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import joinedload

from compass_collector.database import init_db, get_session
from compass_collector.models.intervention import InterventionRecord, QualityFlag
from compass_collector.models.document import Document
from compass_collector.scraper.extraction.field_extractor import FieldExtractor

init_db()
fe = FieldExtractor()
session = get_session()

records = (
    session.query(InterventionRecord)
    .filter(InterventionRecord.organization_name.is_(None))
    .all()
)

total = len(records)
print(f"Fetching full text for {total} records...")

fetched = 0
errors = 0
for i, inv in enumerate(records):
    try:
        doc = session.query(Document).filter_by(id=inv.document_id).first()
        if not doc or not doc.url or not doc.url.startswith("http"):
            errors += 1
            continue

        resp = requests.get(
            doc.url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CompassCollector/1.0)"},
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)[:10000]

        if len(text) < 200:
            continue

        fields = fe.extract_all(text)
        updated = False
        for k, v in fields.items():
            if v is not None and v != [] and v != "":
                if hasattr(inv, k):
                    setattr(inv, k, v)
                    updated = True

        if updated:
            fetched += 1
            new_flags = []
            if not fields.get("organization_name"):
                new_flags.append("missing_organization")
            if not fields.get("intervention_implementation_cost"):
                new_flags.append("missing_implementation_cost")
            if not fields.get("has_baseline"):
                new_flags.append("no_baseline")
            if not fields.get("sample_size"):
                new_flags.append("no_sample_size")
            for flag_name in new_flags:
                session.add(
                    QualityFlag(
                        id=str(uuid.uuid4()),
                        intervention_id=inv.id,
                        flag_name=flag_name,
                    )
                )

        if i % 100 == 0 and i > 0:
            session.commit()
            print(f"  {i}/{total} — {fetched} fetched, {errors} errors")

    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error [{i}]: {str(e)[:80]}")

session.commit()

print(f"\nDone!")
print(f"  Total records: {total}")
print(f"  Full text fetched: {fetched}")
print(f"  Errors: {errors}")

# Re-export
from compass_collector.export.formats import ExportEngine
from compass_collector.config.settings import EXPORTS_DIR
ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
print("Re-exported all data.")
session.close()
