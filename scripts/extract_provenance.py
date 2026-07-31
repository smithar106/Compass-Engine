#!/usr/bin/env python3
"""Provenance-aware batch extraction.

Uses the full provenance-based LLM prompt (implementation detail vs outcome
credibility), stores provenance fields + outcome block on each record, then
classifies using the causal-evidence scoring model.

Usage:
  ./venv/bin/python3 scripts/extract_provenance.py --limit 200
  ./venv/bin/python3 scripts/extract_provenance.py --all
  ./venv/bin/python3 scripts/extract_provenance.py --reprocess
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from compass_collector.database import get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.extraction_llm.llm_extractor import LLM_EXTRACTION_PROMPT
from sqlalchemy import func

KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "sk-4c4a146881a346338565063341319566"
API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


def call_llm(text: str) -> dict:
    """Call DeepSeek with the full provenance prompt."""
    import urllib.request
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": LLM_EXTRACTION_PROMPT + "\n\n" + text[:8000]}],
        "temperature": 0.0,
        "max_tokens": 6000,
    }).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    raw = json.loads(resp.read())["choices"][0]["message"]["content"]
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def save_extraction(doc, parsed: dict) -> bool:
    """Map parsed provenance output into InterventionRecord + MetricRecord."""
    if parsed.get("evidence_tier") == "rejected":
        return False
    org = parsed.get("organization_name")
    if not org:
        return False

    eq = parsed.get("evidence_quality", {})
    ob = parsed.get("outcome_block", {})

    rid = str(uuid.uuid4())
    session = get_session()
    try:
        rec = InterventionRecord(
            id=rid,
            source_id=f"prov-{rid[:8]}",
            document_id=doc.id,
            organization_name=org,
            organization_industry=[parsed.get("organization_industry")] if parsed.get("organization_industry") else [],
            problem_statement=str(parsed.get("business_problem", ""))[:500] or f"Operational transformation at {org}",
            problem_baseline_description=str(parsed.get("baseline_description", ""))[:2000],
            intervention_title=str(parsed.get("intervention_title", ""))[:200],
            intervention_families=[parsed.get("intervention_category", "").lower()] if parsed.get("intervention_category") else [],
            intervention_vendors=parsed.get("intervention_vendors") or [],
            independently_verified=bool(eq.get("independently_verified")),
            vendor_reported=bool(eq.get("is_vendor_reported")),
            has_baseline=bool(ob.get("baseline_metric")),
            has_post_measurement=bool(ob.get("post_metric")),
            measurement_method=str(ob.get("measurement_method", ""))[:500],
            extraction_model=MODEL,
            extractor="provenance_v1",
            extracted_at=datetime.now(timezone.utc),
            review_status="pending",
            # Provenance model
            implementation_provenance=eq.get("implementation_provenance"),
            outcome_provenance=eq.get("outcome_provenance"),
            implementation_detail_score=eq.get("implementation_detail_score"),
            outcome_credibility_score=eq.get("outcome_credibility_score"),
            methodology_detail_score=eq.get("methodology_detail_score"),
            operational_insight_score=eq.get("operational_insight_score"),
            outcome_block=ob,
            source_type=ob.get("source_type"),
            evidence_level=ob.get("evidence_level"),
        )
        session.add(rec)
        for m in parsed.get("outcomes") or []:
            session.add(MetricRecord(
                id=str(uuid.uuid4()),
                intervention_id=rid,
                source_id=rec.source_id,
                metric_name=m.get("metric_name", ""),
                metric_category=m.get("category", ""),
                baseline_value=m.get("baseline_value"),
                post_value=m.get("post_value"),
                absolute_change=m.get("absolute_change"),
                percentage_change=m.get("percentage_change"),
                unit=m.get("unit", ""),
                reported_text=m.get("source_passage", "")[:1000],
                value_type=m.get("value_type", "reported"),
            ))
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def classify(rec, metrics_count: int = 0) -> str:
    """Provenance-aware classification → gold/silver/bronze."""
    prov = rec.implementation_provenance
    gold_provenances = {"government_audited", "peer_reviewed"}
    has_metrics = metrics_count > 0 or bool(rec.outcome_block)
    has_outcomes = has_metrics

    if prov in gold_provenances and has_outcomes:
        ev = rec.evidence_level
        if ev in ("causal", "strong_correlation", "government_audited_outcomes") or \
           (rec.has_baseline and rec.has_post_measurement):
            return "gold"
    if prov in gold_provenances:
        return "silver" if has_outcomes else "bronze"

    # Silver: named org + deployed intervention + described outcomes,
    # source is customer/independent/financial disclosure with detail
    if prov in ("customer_documented", "independently_validated", "financial_disclosure"):
        if has_outcomes:
            return "silver"
        if rec.implementation_detail_score and rec.implementation_detail_score >= 6:
            return "silver"
        return "bronze"

    # Bronze: vendor-documented or unknown
    return "bronze"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", "-l", type=int, default=200)
    parser.add_argument("--all", action="store_true", help="Process all unprocessed")
    parser.add_argument("--reprocess", action="store_true", help="Re-classify existing without re-extracting")
    args = parser.parse_args()

    if args.reprocess:
        session = get_session()
        for rec in session.query(InterventionRecord).filter(InterventionRecord.review_status.in_(["pending", "", None])).all():
            mc = session.query(MetricRecord).filter_by(intervention_id=rec.id).count()
            rec.review_status = classify(rec, mc)
        session.commit()
        t = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
        print(f"Reclassified: {t.get('gold',0)} gold, {t.get('silver',0)} silver, {t.get('bronze',0)} bronze")
        session.close()
        return

    session = get_session()
    extracted = set(r[0] for r in session.query(InterventionRecord.document_id).filter(
        InterventionRecord.document_id.isnot(None)).all() if r[0])
    query = session.query(Document).filter(
        Document.cleaned_text.isnot(None),
        Document.cleaned_text != "",
    )
    if not args.all:
        if extracted:
            query = query.filter(~Document.id.in_(list(extracted)))
        query = query.limit(args.limit)
    else:
        if extracted:
            query = query.filter(~Document.id.in_(list(extracted)))
    docs = query.all()
    session.close()
    print(f"Processing {len(docs)} documents")

    saved = 0
    for i, d in enumerate(docs, 1):
        text = (d.cleaned_text or "")[:8000]
        if len(text) < 300:
            continue
        try:
            parsed = call_llm(text)
            if save_extraction(d, parsed):
                saved += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(docs)}] saved {saved}")
        except Exception:
            pass
        time.sleep(0.3)

    # Classify new records
    session = get_session()
    for rec in session.query(InterventionRecord).filter(InterventionRecord.review_status.in_(["pending", "", None])).all():
        mc = session.query(MetricRecord).filter_by(intervention_id=rec.id).count()
        rec.review_status = classify(rec, mc)
    session.commit()

    t = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
    total = session.query(InterventionRecord).count()
    print(f"\nFINAL: {total} total")
    for x in ["gold", "silver", "bronze"]:
        print(f"  {x}: {t.get(x, 0)}")
    print(f"Gaps: gold={max(0,300-t.get('gold',0))} silver={max(0,300-t.get('silver',0))} bronze={max(0,300-t.get('bronze',0))}")
    session.close()


if __name__ == "__main__":
    main()
