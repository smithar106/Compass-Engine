#!/usr/bin/env python3
"""Batch extraction using env key. Processes unprocessed documents."""
import os, sys, json, uuid, urllib.request
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compass_collector.database import get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from sqlalchemy import func

# Load key from env
KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
if not KEY or "YOUR_KEY" in KEY:
    KEY = "sk-4c4a146881a346338565063341319566"

API = "https://api.deepseek.com/chat/completions"
PROMPT = '{"organization_name":"","organization_industry":"","business_function":"","intervention_title":"","intervention_category":"Workflow_Automation/AI/Software/Process_Redesign/Staffing/Hybrid","outcomes":[{"metric_name":"","category":"time/cost/revenue/quality","percentage_change":null}],"evidence_quality":{"independently_verified":false,"is_vendor_reported":true}}\nIf none: {"rejected":true}\n'

session = get_session()
extracted = set(r[0] for r in session.query(InterventionRecord.document_id).filter(InterventionRecord.document_id.isnot(None)).all() if r[0])
docs = session.query(Document).filter(Document.cleaned_text.isnot(None), ~Document.id.in_(extracted) if extracted else True).limit(200).all()
session.close()
print(f"Processing {len(docs)} documents")

saved = 0
for d in docs:
    text = (d.cleaned_text or "")[:3000]
    if len(text) < 300:
        continue
    try:
        body = json.dumps({"model": "deepseek-chat", "messages": [{"role": "user", "content": PROMPT + text}], "temperature": 0.0, "max_tokens": 600}).encode()
        req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
        resp = urllib.request.urlopen(req, timeout=25)
        raw = json.loads(resp.read())["choices"][0]["message"]["content"]
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1].strip() if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:].strip()
        parsed = json.loads(raw.strip())
        if parsed.get("rejected") or not parsed.get("organization_name"):
            continue
        
        org = parsed["organization_name"]
        rid = str(uuid.uuid4())
        industry = parsed.get("organization_industry") or []
        if isinstance(industry, str):
            industry = [industry]
        
        session = get_session()
        rec = InterventionRecord(
            id=rid, source_id=f"ex-{rid[:8]}", document_id=d.id,
            organization_name=org, organization_industry=industry,
            problem_statement=f"Operational transformation at {org}"[:500],
            intervention_title=str(parsed.get("intervention_title", ""))[:200],
            intervention_families=[parsed.get("intervention_category", "").lower()] if parsed.get("intervention_category") else [],
            independently_verified=parsed.get("evidence_quality", {}).get("independently_verified", False),
            vendor_reported=parsed.get("evidence_quality", {}).get("is_vendor_reported", True),
            extraction_model="deepseek-chat", extractor="env_batch_v3",
            extracted_at=datetime.now(timezone.utc), review_status="pending",
        )
        session.add(rec)
        for m in parsed.get("outcomes") or []:
            session.add(MetricRecord(
                id=str(uuid.uuid4()), intervention_id=rid, source_id=rec.source_id,
                metric_name=m.get("metric_name", ""), metric_category=m.get("category", ""),
                percentage_change=m.get("percentage_change"), unit=m.get("unit", ""),
                reported_text=m.get("metric_name", ""), value_type="reported",
            ))
        session.commit()
        session.close()
        saved += 1
        if saved % 20 == 0:
            print(f"  Saved {saved}")
    except Exception as e:
        pass

# Classify all
session = get_session()
for rec in session.query(InterventionRecord).filter(InterventionRecord.review_status.in_(["pending", "", None])).all():
    mc = session.query(MetricRecord).filter_by(intervention_id=rec.id)
    has_q = mc.filter(MetricRecord.percentage_change.isnot(None) | MetricRecord.absolute_change.isnot(None)).count() > 0
    score = 20 if has_q else 10 if mc.count() > 0 else 0
    score += 15 if rec.independently_verified else 0
    score += 10 if rec.has_baseline else 0
    score += 10 if rec.intervention_implementation_time_value else 0
    score += 10 if rec.organization_employee_count else 0
    score += 10 if rec.organization_industry and rec.organization_industry not in ("[]", "") else 0
    score -= 10 if rec.vendor_reported and not rec.independently_verified else 0
    rec.review_status = "gold" if score >= 50 else "silver" if score >= 25 else "bronze"
session.commit()

t = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
total = session.query(InterventionRecord).count()
print(f"\nFINAL: {total} total")
for x in ["gold", "silver", "bronze"]:
    print(f"  {x}: {t.get(x, 0)}")
print(f"Gaps: gold={max(0,300-t.get('gold',0))} silver={max(0,300-t.get('silver',0))} bronze={max(0,300-t.get('bronze',0))}")
session.close()
