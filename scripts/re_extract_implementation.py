#!/usr/bin/env python3
"""Re-extract implementation detail from existing vendor story records.

724 vendor_documented records were extracted before the Implementation
Intelligence fields existed. This script re-extracts those documents
with the enhanced prompt and captures per-field provenance.

Does NOT create duplicate records — updates existing records in place.

Usage:
  ./venv/bin/python3 scripts/re_extract_implementation.py --limit 30
  ./venv/bin/python3 scripts/re_extract_implementation.py --all --batch-size 50
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import get_session, engine
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord
from compass_collector.extraction_llm.llm_extractor import LLM_EXTRACTION_PROMPT
from sqlalchemy import text, func

def _get_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY", "")
    if k and k not in ("YOUR_KEY_HERE", "", " "):
        return k
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if k and k not in ("YOUR_KEY_HERE", "", " "):
        return k
    return "sk-4c4a146881a346338565063341319566"

KEY = _get_key()
API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

IMPLEMENTATION_FIELDS = [
    "pilot_structure", "rollout_strategy", "implementation_partner",
    "executive_sponsor", "implementation_team_structure", "intervention_vendors",
    "governance_model", "change_management", "training_approach",
    "adoption_approach", "success_criteria", "lessons_learned",
    "implementation_duration_value", "budget_range", "implementation_pattern",
]


def call_llm(text: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": LLM_EXTRACTION_PROMPT + "\n\n" + text[:12000]}],
        "temperature": 0.0, "max_tokens": 8000,
    }).encode()
    req = urllib.request.Request(API, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    resp = urllib.request.urlopen(req, timeout=120)
    raw = json.loads(resp.read())["choices"][0]["message"]["content"]
    if "```" in raw:
        parts = raw.split("```"); raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())


def capture_provenance(parsed: dict, doc_text: str, doc_id: str, doc_url: str) -> list[dict]:
    provenance = []
    for field in IMPLEMENTATION_FIELDS:
        val = parsed.get(field)
        if val is None:
            continue
        if isinstance(val, str) and len(val.strip()) < 5:
            continue
        if isinstance(val, list) and len(val) == 0:
            continue

        search = (val[:50] if isinstance(val, str) else (str(val[0])[:50] if (isinstance(val, list) and val) else ""))
        supporting = ""
        idx = doc_text.lower().find(search.lower()) if search else -1
        if idx >= 0:
            supporting = doc_text[max(0, idx - 100): idx + len(search) + 200]
        explicit = bool(supporting and len(supporting) > 20)

        provenance.append({
            "field_name": field,
            "value": val[:500] if isinstance(val, str) else val,
            "supporting_text": supporting[:1000],
            "source_id": doc_id,
            "source_url": doc_url,
            "source_section": "",
            "extraction_confidence": "medium",
            "explicit": explicit,
        })
    return provenance


def classify_richness(provenance: list[dict]) -> str:
    fields = set(p.get("field_name") for p in provenance if p.get("explicit"))
    count = len(fields)
    if count >= 4: return "rich"
    elif count >= 2: return "usable"
    return "thin"


def update_record(rec: InterventionRecord, parsed: dict, provenance: list[dict]):
    eq = parsed.get("evidence_quality", {})
    ob = parsed.get("outcome_block", {})

    rec.implementation_provenance = rec.implementation_provenance or eq.get("implementation_provenance", "vendor_documented")
    rec.outcome_provenance = rec.outcome_provenance or eq.get("outcome_provenance")
    rec.implementation_detail_score = rec.implementation_detail_score or eq.get("implementation_detail_score")
    rec.outcome_credibility_score = rec.outcome_credibility_score or eq.get("outcome_credibility_score")
    rec.methodology_detail_score = rec.methodology_detail_score or eq.get("methodology_detail_score")
    rec.operational_insight_score = rec.operational_insight_score or eq.get("operational_insight_score")
    rec.outcome_block = rec.outcome_block or ob
    rec.source_type = rec.source_type or ob.get("source_type")
    rec.evidence_level = rec.evidence_level or ob.get("evidence_level")

    rec.executive_sponsor = str(parsed.get("executive_sponsor", ""))[:200] or rec.executive_sponsor
    rec.pilot_structure = str(parsed.get("pilot_structure", ""))[:2000] or rec.pilot_structure
    rec.training_approach = str(parsed.get("training_approach", ""))[:2000] or rec.training_approach
    rec.adoption_approach = str(parsed.get("adoption_approach", ""))[:2000] or rec.adoption_approach
    rec.implementation_team_structure = str(parsed.get("implementation_team_structure", ""))[:2000] or rec.implementation_team_structure
    rec.budget_range = str(parsed.get("budget_range", ""))[:100] or rec.budget_range
    rec.key_decision_makers = parsed.get("key_decision_makers") or rec.key_decision_makers
    rec.success_criteria = parsed.get("success_criteria") or rec.success_criteria
    rec.implementation_partner = parsed.get("implementation_partner") or rec.implementation_partner
    rec.implementation_pattern = parsed.get("implementation_pattern") or rec.implementation_pattern
    rec.lessons_learned = parsed.get("lessons_learned") or rec.lessons_learned
    rec.change_management = str(parsed.get("change_management", ""))[:2000] or rec.change_management
    rec.rollout_strategy = str(parsed.get("rollout_strategy", ""))[:2000] or rec.rollout_strategy
    rec.governance_model = str(parsed.get("governance_model", ""))[:1000] or rec.governance_model

    rec.implementation_field_provenance = provenance
    rec.implementation_richness = classify_richness(provenance)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", "-l", type=int, default=30)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--batch-size", "-b", type=int, default=50)
    args = parser.parse_args()

    from compass_collector.database import init_db
    from compass_collector.models.intervention import InterventionRecord
    init_db()

    session = get_session()
    # Only select records that have documents with text
    from sqlalchemy import text as sa_text
    doc_ids_with_text = set(
        row[0] for row in session.execute(
            sa_text("SELECT id FROM documents WHERE cleaned_text IS NOT NULL AND cleaned_text != ''")
        ).fetchall()
    )
    query = session.query(InterventionRecord).filter(
        InterventionRecord.implementation_provenance == "vendor_documented",
        InterventionRecord.document_id.in_(doc_ids_with_text) if doc_ids_with_text else False,
    ).filter(
        (InterventionRecord.implementation_field_provenance == None) |
        (InterventionRecord.implementation_field_provenance == "[]")
    )

    total = query.count()
    if not args.all:
        query = query.limit(args.limit)
    records = query.all()

    print(f"Re-extracting implementation detail from {len(records)} vendor records ({total} total eligible)")
    print()

    updated = 0
    rich = usable = thin = 0
    errors = 0

    for i, rec in enumerate(records):
        try:
            doc = session.query(Document).filter(Document.id == rec.document_id).first()
            if not doc or not doc.cleaned_text:
                continue

            text = doc.cleaned_text
            parsed = call_llm(text)
            prov = capture_provenance(parsed, text, doc.id, doc.url or "")
            update_record(rec, parsed, prov)

            r = classify_richness(prov)
            if r == "rich": rich += 1
            elif r == "usable": usable += 1
            else: thin += 1

            updated += 1
            if i % 10 == 0:
                session.commit()
                print(f"  [{i+1}/{len(records)}] updated {updated} (rich={rich}, usable={usable}, thin={thin})")

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [{i+1}] error: {e}")
        time.sleep(0.3)

    session.commit()

    # Reclassify
    from scripts.extract_provenance import classify
    recls = 0
    for rec in session.query(InterventionRecord).filter(InterventionRecord.review_status.in_(["pending", "", None])).all():
        rec.review_status = classify(rec, 0)
        recls += 1
    session.commit()

    # Final stats
    total = session.query(InterventionRecord).count()
    rich_c = session.query(InterventionRecord).filter(InterventionRecord.implementation_richness == "rich").count()
    usable_c = session.query(InterventionRecord).filter(InterventionRecord.implementation_richness == "usable").count()
    thin_c = session.query(InterventionRecord).filter(InterventionRecord.implementation_richness == "thin").count()

    # Field fill rates
    field_counts = Counter()
    for rec in session.query(InterventionRecord).filter(InterventionRecord.implementation_field_provenance.isnot(None)).all():
        for p in (rec.implementation_field_provenance or []):
            if p.get("explicit"):
                field_counts[p.get("field_name", "")] += 1
    fill_rates = {f: round(c / max(total, 1), 2) for f, c in field_counts.most_common()}

    session.close()

    print(f"\n{'='*60}")
    print(f"RE-EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Updated: {updated} records")
    print(f"  Errors:  {errors}")
    print(f"  Rich:    {rich} (4+ fields)")
    print(f"  Usable:  {usable} (2-3 fields)")
    print(f"  Thin:    {thin} (0-1 fields)")
    print(f"\n  Graph totals:")
    print(f"    Rich:   {rich_c}")
    print(f"    Usable: {usable_c}")
    print(f"    Thin:   {thin_c}")
    print(f"    Unclassified: {total - rich_c - usable_c - thin_c}")
    print(f"\n  Field fill rates (explicit only):")
    for f, rate in sorted(fill_rates.items(), key=lambda x: -x[1]):
        bar = "█" * int(rate * 50)
        print(f"    {f:<35} {rate:.0%} {bar}")


if __name__ == "__main__":
    main()
