#!/usr/bin/env python3
"""Multi-intervention extraction for roundup/case-study-library documents.

Roundup pages (e.g. '21 Examples of Digital Transformation') describe MANY
implementations in a single document. This script prompts the LLM to extract
ALL interventions (up to N per document) so we don't waste a 60-case-study
page on a single record.

Usage:
  ./venv/bin/python3 scripts/extract_multi.py --urls-file data/roundup_urls.txt
  ./venv/bin/python3 scripts/extract_multi.py --limit 5
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.extraction_llm.llm_extractor import LLM_EXTRACTION_PROMPT

KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "sk-4c4a146881a346338565063341319566"
API = "https://api.deepseek.com/chat/completions"

MULTI_PROMPT = """You are a research analyst extracting operational transformation records from a case study roundup for Compass.

This document describes MULTIPLE real-world implementations. Extract ALL distinct implementations described, up to {max_n} of the most significant ones (those with named organizations and quantified outcomes).

For EACH implementation, extract:
{{
  "organization_name": "",
  "organization_industry": "",
  "business_function": "sales/marketing/customer_support/finance/hr/it/engineering/operations/supply_chain/legal/compliance/product/procurement/research",
  "business_problem": "",
  "workflow": "",
  "intervention_title": "",
  "intervention_category": "Workflow_Automation/AI/Software/Process_Redesign/Staffing/Hybrid",
  "intervention_vendors": [],
  "baseline_description": "",
  "implementation_status": "completed/in_progress/abandoned",
  "implementation_duration_value": 0,
  "implementation_duration_unit": "",
  "implementation_partner": [],
  "implementation_pattern": [],
  "lessons_learned": [],
  "change_management": "",
  "rollout_strategy": "",
  "governance_model": "",
  "outcomes": [
    {{
      "metric_name": "",
      "category": "time/cost/revenue/quality/satisfaction/adoption/efficiency/productivity",
      "baseline_value": null,
      "post_value": null,
      "absolute_change": null,
      "percentage_change": null,
      "unit": "",
      "direction": "positive/negative",
      "value_type": "observed/projected/estimated",
      "source_passage": "EXACT QUOTE from the text"
    }}
  ],
  "outcome_block": {{
    "baseline_metric": "",
    "post_metric": "",
    "percent_change": null,
    "time_period": "",
    "organization": "",
    "implementation": "",
    "measurement_method": "",
    "confidence": "high/medium/low",
    "source_type": "vendor_case_study/company_blog/independent_roundup/government_report/academic_paper",
    "evidence_level": "causal/strong_correlation/correlational/directional"
  }},
  "evidence_quality": {{
    "is_vendor_reported": true/false,
    "independently_verified": true/false,
    "source_credibility": "high/medium/low",
    "implementation_detail_score": 1-10,
    "outcome_credibility_score": 1-10,
    "methodology_detail_score": 1-10,
    "operational_insight_score": 1-10,
    "implementation_provenance": "vendor_documented/customer_documented/independently_validated/government_audited/peer_reviewed/financial_disclosure",
    "outcome_provenance": "vendor_reported/independently_verified/peer_reviewed_methodology/government_audited_outcomes"
  }}
}}

If the text contains NO real implementations, respond: {{"extractions": []}}

OUTPUT FORMAT: Return ONLY a JSON object with an "extractions" array containing each implementation record.

SOURCE TEXT:
"""


def call_multi(text: str, max_n: int = 10) -> list[dict]:
    import urllib.request
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": MULTI_PROMPT.format(max_n=max_n) + "\n\n" + text[:12000]}],
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

    def repair_json(text: str) -> list[dict]:
        text = text.strip()
        try:
            return json.loads(text).get("extractions", [])
        except json.JSONDecodeError as e:
            print(f"    json parse failed at pos {e.pos}: {e.msg[:60]}")
            truncated = text[:e.pos]
            balance = truncated.count("{") - truncated.count("}")
            closers = "}" * max(1, balance)
            brackets = truncated.count("[") - truncated.count("]")
            closers += "]" * max(1, brackets)
            try:
                return json.loads(truncated + closers).get("extractions", [])
            except json.JSONDecodeError:
                pass
        items = []
        depth = pos = 0
        start = -1
        while pos < len(text):
            c = text[pos]
            if c == "{":
                if depth == 0:
                    start = pos
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        items.append(json.loads(text[start:pos + 1]))
                    except json.JSONDecodeError:
                        pass
                    start = -1
            pos += 1
        return items

    data = {"extractions": repair_json(raw.strip())}
    return data.get("extractions", [])


def classify(prov: str, outcomes: list, ob: dict, detail_score: int, partner: list = None, lessons: list = None, rollout: str = None) -> str:
    gold_provs = {"government_audited", "peer_reviewed", "financial_disclosure"}
    has_outcomes = bool(outcomes) or bool(ob.get("baseline_metric"))
    if prov in gold_provs and has_outcomes:
        if ob.get("confidence") == "high" or (ob.get("baseline_metric") and ob.get("post_metric")):
            return "gold"
        return "silver"
    if prov in ("customer_documented", "independently_validated"):
        return "silver" if has_outcomes else ("silver" if detail_score and detail_score >= 6 else "bronze")
    if prov == "vendor_documented":
        ds = detail_score or 0
        if ds >= 7 or (ds >= 5 and (bool(partner) or bool(lessons) or bool(rollout))):
            return "silver"
        return "bronze"
    return "bronze"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls-file", "-f", help="File with URLs to process")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Max docs per run")
    parser.add_argument("--max-per-doc", "-m", type=int, default=10, help="Max extractions per doc")
    args = parser.parse_args()

    session = get_session()
    query = session.query(Document).filter(
        Document.cleaned_text.isnot(None),
        Document.cleaned_text != "",
    )
    if args.urls_file:
        with open(args.urls_file) as f:
            urls = [ln.strip() for ln in f if ln.strip()]
        query = query.filter(Document.url.in_(urls))
    docs = query.limit(args.limit).all()
    session.close()
    print(f"Processing {len(docs)} documents")

    total_saved = 0
    for i, d in enumerate(docs, 1):
        # Skip docs already multi-extracted (but allow single-extracted roundups to be re-run)
        session = get_session()
        existing_multi = session.query(InterventionRecord).filter(
            InterventionRecord.document_id == d.id,
            InterventionRecord.extractor == "multi_v1",
        ).count()
        session.close()
        if existing_multi > 0:
            print(f"  [{i}/{len(docs)}] ⏭ {d.title[:50]} (already multi-extracted {existing_multi})")
            continue

        text = (d.cleaned_text or "")[:12000]
        if len(text) < 500:
            continue
        try:
            extractions = call_multi(text, max_n=args.max_per_doc)
            print(f"  [{i}/{len(docs)}] {d.title[:50]} -> {len(extractions)} extractions")
            if not extractions:
                continue
            for p in extractions:
                org = p.get("organization_name")
                if not org:
                    continue
                eq = p.get("evidence_quality", {})
                ob = p.get("outcome_block", {})
                prov = eq.get("implementation_provenance")
                tier = classify(prov, p.get("outcomes", []), ob, eq.get("implementation_detail_score"),
                                p.get("implementation_partner"), p.get("lessons_learned"),
                                p.get("rollout_strategy"))
                rid = str(uuid.uuid4())
                session = get_session()
                try:
                    rec = InterventionRecord(
                        id=rid, source_id=f"multi-{rid[:8]}", document_id=d.id,
                        organization_name=org,
                        organization_industry=[p.get("organization_industry")] if p.get("organization_industry") else [],
                        problem_statement=str(p.get("business_problem", ""))[:500] or f"Operational transformation at {org}",
                        problem_baseline_description=str(p.get("baseline_description", ""))[:2000],
                        intervention_title=str(p.get("intervention_title", ""))[:200],
                        intervention_families=[p.get("intervention_category", "").lower()] if p.get("intervention_category") else [],
                        intervention_vendors=p.get("intervention_vendors") or [],
                        independently_verified=bool(eq.get("independently_verified")),
                        vendor_reported=bool(eq.get("is_vendor_reported")),
                        has_baseline=bool(ob.get("baseline_metric")),
                        has_post_measurement=bool(ob.get("post_metric")),
                        measurement_method=str(ob.get("measurement_method", ""))[:500],
                        extraction_model="deepseek-chat", extractor="multi_v1",
                        extracted_at=datetime.now(timezone.utc), review_status=tier,
                        implementation_provenance=prov,
                        outcome_provenance=eq.get("outcome_provenance"),
                        implementation_detail_score=eq.get("implementation_detail_score"),
                        outcome_credibility_score=eq.get("outcome_credibility_score"),
                        methodology_detail_score=eq.get("methodology_detail_score"),
                        operational_insight_score=eq.get("operational_insight_score"),
                        outcome_block=ob,
                        source_type=ob.get("source_type"),
                        evidence_level=ob.get("evidence_level"),
                        implementation_partner=p.get("implementation_partner") or [],
                        implementation_pattern=p.get("implementation_pattern") or [],
                        lessons_learned=p.get("lessons_learned") or [],
                        change_management=str(p.get("change_management", ""))[:2000],
                        rollout_strategy=str(p.get("rollout_strategy", ""))[:2000],
                        governance_model=str(p.get("governance_model", ""))[:1000],
                    )
                    session.add(rec)
                    for m in p.get("outcomes") or []:
                        session.add(MetricRecord(
                            id=str(uuid.uuid4()), intervention_id=rid, source_id=rec.source_id,
                            metric_name=m.get("metric_name", ""), metric_category=m.get("category", ""),
                            baseline_value=m.get("baseline_value"), post_value=m.get("post_value"),
                            absolute_change=m.get("absolute_change"), percentage_change=m.get("percentage_change"),
                            unit=m.get("unit", ""), reported_text=m.get("source_passage", "")[:1000],
                            value_type=m.get("value_type", "reported"),
                        ))
                    session.commit()
                    total_saved += 1
                except Exception:
                    session.rollback()
                finally:
                    session.close()
        except Exception as e:
            print(f"    error: {e}")
        time.sleep(0.5)

    # Print final counts
    from sqlalchemy import func
    session = get_session()
    t = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
    total = session.query(InterventionRecord).count()
    print(f"\nFINAL: {total} total")
    for x in ["gold", "silver", "bronze"]:
        print(f"  {x}: {t.get(x, 0)}")
    print(f"Gaps: gold={max(0,300-t.get('gold',0))} silver={max(0,300-t.get('silver',0))} bronze={max(0,300-t.get('bronze',0))}")
    session.close()


if __name__ == "__main__":
    main()
