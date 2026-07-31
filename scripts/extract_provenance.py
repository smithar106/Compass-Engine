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


def select_text_window(text: str) -> str:
    """Select the best text window for extraction, skipping boilerplate."""
    if not text:
        return ""
    tl = text.lower()
    # SEC filing: target Item 7 (MD&A) for financial outcomes
    for pattern in ["Item 7.", "ITEM 7."]:
        idx = text.find(pattern)
        if idx >= 5000 and idx < len(text) * 0.5:
            return text[idx: idx + 16000]
    # SEC filing: Item 1 Business  
    for pattern in ["Item 1.", "ITEM 1."]:
        idx = text.find(pattern)
        if idx >= 2000 and idx < len(text) * 0.3:
            return text[idx: idx + 16000]
    # Short doc: use from start
    if len(text) <= 20000:
        return text[:16000]
    # Long doc: skip first 2K (covers/ToC), search for substantive content
    # Look for AI/technology discussion start
    for kw in ["artificial intelligence", "machine learning"]:
        idx = tl.find(kw)
        if idx > 2000 and idx < len(text) * 0.5:
            return text[max(0, idx - 500): idx + 15500]
    return text[2000: 18000]


def call_llm(text: str) -> dict:
    """Call DeepSeek with the full provenance prompt."""
    import urllib.request
    window = select_text_window(text)
    if len(window) < 300:
        window = text[:16000]
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": LLM_EXTRACTION_PROMPT + "\n\n" + window[:12000]}],
        "temperature": 0.0,
        "max_tokens": 8000,
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
            # Implementation decision-support fields
            implementation_partner=parsed.get("implementation_partner") or [],
            implementation_pattern=parsed.get("implementation_pattern") or [],
            lessons_learned=parsed.get("lessons_learned") or [],
            change_management=str(parsed.get("change_management", ""))[:2000],
            rollout_strategy=str(parsed.get("rollout_strategy", ""))[:2000],
            governance_model=str(parsed.get("governance_model", ""))[:1000],
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
    """Provenance-aware classification → gold/silver/bronze.

    GOLD = high-confidence causal implementation evidence, per the product
    contract. This is NOT about who wrote it — it's whether the evidence
    supports a credible causal claim:
      * government audit with measured outcomes
      * public company SEC filing discussing implementation results with
        quantified before/after
      * peer-reviewed implementation study
      * randomized/quasi-experimental evaluation
      * independent evaluator with measured outcomes
    """
    prov = rec.implementation_provenance
    gold_provenances = {"government_audited", "peer_reviewed", "financial_disclosure"}
    has_metrics = metrics_count > 0 or bool(rec.outcome_block)
    has_outcomes = has_metrics

    if prov in gold_provenances and has_outcomes:
        ev = rec.evidence_level
        ob = rec.outcome_block or {}
        # Gold requires measured baseline AND post (or explicit causal claim)
        has_baseline_post = bool(rec.has_baseline and rec.has_post_measurement)
        strong_signal = ev in ("causal", "strong_correlation", "government_audited_outcomes")
        high_conf_ob = ob.get("confidence") == "high"
        if has_baseline_post or strong_signal or high_conf_ob:
            return "gold"
    if prov in gold_provenances:
        return "silver" if has_outcomes else "bronze"

    # Silver: named org + deployed intervention + described outcomes,
    # source is customer/independent/financial disclosure with detail.
    # Also: vendor customer stories with rich implementation detail
    # (implementation partner, rollout strategy, lessons learned) qualify
    # as Silver because they carry the "connective tissue" of the graph.
    if prov in ("customer_documented", "independently_validated"):
        if has_outcomes:
            return "silver"
        if rec.implementation_detail_score and rec.implementation_detail_score >= 6:
            return "silver"
        return "bronze"
    if prov == "vendor_documented":
        detail_score = rec.implementation_detail_score or 0
        has_partner = bool(rec.implementation_partner)
        has_lessons = bool(rec.lessons_learned)
        has_rollout = bool(rec.rollout_strategy)
        if detail_score >= 7 or (detail_score >= 5 and (has_partner or has_lessons or has_rollout)):
            return "silver"
        return "bronze"

    # Bronze: unknown provenance
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
        text = d.cleaned_text or ""
        if len(text) < 300:
            continue
        try:
            parsed = call_llm(text)
            if save_extraction(d, parsed):
                saved += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(docs)}] saved {saved}")
        except Exception as e:
            print(f"  [{i}/{len(docs)}] error: {e}")
            time.sleep(1)
            continue
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
