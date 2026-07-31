#!/usr/bin/env python3
"""Fast extraction — one doc at a time, strict timeout, save after each."""
import sys, json, uuid, signal, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compass_collector.database import get_session, init_db
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
import urllib.request, urllib.error
from sqlalchemy import func

API_KEY = "sk-4c4a146881a346338565063341319566"
API_URL = "https://api.deepseek.com/chat/completions"

PROMPT = """You extract operational transformation records from business case studies.

Return ONLY valid JSON. No markdown, no explanation.

Fields to extract:
{
  "organization_name": "company name",
  "organization_industry": "best single industry match",
  "organization_employee_count": 0,
  "business_problem": "what problem was solved",
  "business_function": "one: sales/marketing/customer_support/finance/hr/it/engineering/operations/supply_chain/legal",
  "workflow": "specific process name",
  "intervention_title": "what was deployed",
  "intervention_category": "Workflow_Automation/AI/Software/Process_Redesign/Staffing/Hybrid",
  "intervention_vendors": ["vendor names if mentioned"],
  "baseline_description": "before state",
  "implementation_duration_value": 0,
  "implementation_duration_unit": "weeks/months",
  "outcomes": [{"metric_name": "...", "category": "time/cost/revenue/quality", "percentage_change": null, "absolute_change": null, "unit": "%/hours/dollars"}],
  "result_summary": "one sentence",
  "evidence_quality": {"independently_verified": false, "is_vendor_reported": true, "source_credibility": "medium"}
}

If no real implementation, return: {"rejected": true, "reason": "..."}

TEXT:"""

def extract(text, timeout=20):
    import json
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": PROMPT + "\n\n" + text[:4000]}], "temperature": 0.0, "max_tokens": 1000}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        if content.startswith("```"): content = content.split("```")[1]
        if content.startswith("json"): content = content[4:]
        return json.loads(content.strip())
    except Exception as e:
        return {"rejected": True, "reason": str(e)[:60]}

init_db()
session = get_session()

# Delete old v2/v3 records
old = session.query(InterventionRecord).filter(InterventionRecord.extractor.in_(["llm_extraction", "llm_extraction_v2", "llm_extraction_v3"])).all()
for rec in old:
    session.query(MetricRecord).filter_by(intervention_id=rec.id).delete()
    session.delete(rec)
session.commit()
print(f"Deleted {len(old)} old records")

# Get docs WITH text content
docs = session.query(Document).filter(Document.cleaned_text.isnot(None)).order_by(Document.id.desc()).limit(200).all()
print(f"Loaded {len(docs)} documents")

saved = 0
skipped = 0
errors = 0

for i, doc in enumerate(docs):
    text = (doc.cleaned_text or "")[:4000]
    if len(text) < 300:
        skipped += 1
        continue
    
    result = extract(text, timeout=25)
    
    if result.get("rejected"):
        skipped += 1
        if i % 20 == 0:
            print(f"  [{i}] rejected: {result.get('reason','')[:40]}")
        continue
    
    org = result.get("organization_name", "")
    if not org:
        skipped += 1
        continue
    
    rid = str(uuid.uuid4())
    industry = result.get("organization_industry") or []
    if isinstance(industry, str): industry = [industry]
    bfunc = result.get("business_function", "")
    eq = result.get("evidence_quality") or {}
    
    rec = InterventionRecord(id=rid, source_id=f"ex-{rid[:8]}",
        organization_name=org, organization_industry=industry,
        problem_business_function=[bfunc] if bfunc else [],
        problem_statement=str(result.get("business_problem", ""))[:500],
        intervention_title=str(result.get("intervention_title", ""))[:200],
        intervention_families=[result.get("intervention_category", "").lower()] if result.get("intervention_category") else [],
        intervention_vendors=result.get("intervention_vendors") or [],
        intervention_implementation_time_value=result.get("implementation_duration_value") or None,
        intervention_implementation_time_unit=result.get("implementation_duration_unit"),
        has_baseline=bool(result.get("baseline_description")),
        has_post_measurement=True,
        independently_verified=eq.get("independently_verified", False),
        vendor_reported=eq.get("is_vendor_reported", False),
        extraction_model="deepseek-chat", extractor="direct_extract",
        extracted_at=datetime.now(timezone.utc), review_status="pending")
    session.add(rec)
    
    for m in result.get("outcomes") or []:
        session.add(MetricRecord(id=str(uuid.uuid4()), intervention_id=rid,
            source_id=rec.source_id,
            metric_name=m.get("metric_name", ""),
            metric_category=m.get("category", ""),
            absolute_change=m.get("absolute_change"),
            percentage_change=m.get("percentage_change"),
            unit=m.get("unit", ""),
            reported_text=m.get("metric_name", ""),
            value_type="reported"))
    
    saved += 1
    if saved % 10 == 0:
        session.commit()
        print(f"  [{i+1}/{len(docs)}] ✅ {saved} saved (last: {org[:40]})")

session.commit()
print(f"\n=== Done: {saved} saved, {skipped} skipped, {errors} errors ===")

total = session.query(InterventionRecord).count()
tiers = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
print(f"Total implementations: {total}")
for t in ["gold", "silver", "bronze"]:
    print(f"  {t}: {tiers.get(t, 0)}")
session.close()
