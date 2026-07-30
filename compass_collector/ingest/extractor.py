"""Structured evidence extraction from parsed documents.

Takes a normalized InputDocument and extracts EvidenceClaim objects
using the configured LLM provider.
"""

import json
import logging
import hashlib
import uuid
from typing import Optional, List
from datetime import datetime, timezone

from compass_collector.ingest import (
    InputDocument, EvidenceClaim, ExtractionResult, EvidenceQuality,
    Problem, Intervention, Organization, Implementation, Outcome, Metric,
    SourceLocator, ReviewStatus, ClaimType, InterventionType, MetricCategory,
    OutcomeDirection,
)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are extracting structured evidence about operational transformations from business documents.

Analyze the document below and extract ALL claims about real-world problems, interventions, implementations, and outcomes.

For each claim, return a JSON object with these fields:
{
  "claim_type": "problem|intervention|implementation|outcome|organization",
  "claim_text": "The specific claim",
  "organization": {"name": "", "industry": [], "employee_count": null},
  "problem": {"name": "", "description": "", "business_function": []},
  "intervention": {"name": "", "intervention_type": "workflow_automation|ai|software|process_redesign|staffing|hybrid", "vendors": []},
  "implementation": {"duration_value": null, "duration_unit": "", "scope": ""},
  "outcome": {"metric": {"name": "", "category": "time|cost|revenue|quality|satisfaction|adoption|efficiency|productivity", "percentage_change": null, "absolute_change": null, "unit": ""}, "summary": ""},
  "evidence_quality": {"is_independent": false, "is_vendor_reported": true, "has_baseline": false, "sample_size": null},
  "supporting_excerpt": "Exact quote from the text supporting this claim"
}

Rules:
- Return a JSON array of claims. Max 10 claims.
- Only extract claims that are EXPLICITLY supported by the text.
- If no operational transformation evidence is found, return an empty array [].
- Extract quantitative outcomes wherever possible (percentages, dollar amounts, time savings).
- For organization.industry, choose from: healthcare, finance, banking, insurance, manufacturing, retail, technology, telecommunications, energy, government, education, logistics, transportation, hospitality, media, agriculture, pharmaceuticals, construction, aerospace, automotive, professional_services, nonprofit.
- For metric.category, choose from: time, cost, revenue, quality, satisfaction, adoption, efficiency, productivity.

DOCUMENT:
"""


def extract_claims(document: InputDocument, api_key: str, model: str = "deepseek-chat") -> ExtractionResult:
    """Extract evidence claims from a parsed document using the LLM."""
    import urllib.request

    # Prepare document text from sections
    doc_text = ""
    for s in document.sections[:20]:
        doc_text += f"\n## {s.heading}\n{s.text}\n"

    if not doc_text.strip():
        doc_text = document.raw_text[:15000]

    doc_text = doc_text[:12000]

    prompt = EXTRACTION_PROMPT + "\n" + doc_text
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 4000,
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        token_usage = result.get("usage", {}).get("total_tokens", 0)
    except Exception as e:
        return ExtractionResult(
            document_id=document.document_id,
            errors=[str(e)],
        )

    # Parse JSON from LLM response
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1] if "```" in raw else raw
    if raw.startswith("json"):
        raw = raw[4:]
    raw = raw.strip()

    try:
        raw_claims = json.loads(raw)
    except json.JSONDecodeError:
        return ExtractionResult(
            document_id=document.document_id,
            raw_llm_output=content,
            errors=[f"Failed to parse LLM output as JSON: {raw[:200]}"],
        )

    if not isinstance(raw_claims, list):
        raw_claims = [raw_claims]

    # Convert raw claims to typed EvidenceClaim objects
    claims = []
    for rc in raw_claims:
        if not isinstance(rc, dict) or not rc.get("claim_text"):
            continue

        claim = _raw_to_claim(rc, document)
        if claim:
            claims.append(claim)

    # Calculate approximate cost
    input_tokens = token_usage or len(prompt.split())
    cost = (input_tokens * 0.00000014) + (1000 * 0.00000056)  # DeepSeek pricing

    return ExtractionResult(
        document_id=document.document_id,
        claims=claims,
        raw_llm_output=content,
        extraction_model=model,
        prompt_version="v1",
        token_usage=input_tokens,
        cost=cost,
    )


def _raw_to_claim(rc: dict, document: InputDocument) -> Optional[EvidenceClaim]:
    """Convert a raw LLM dict to a typed EvidenceClaim."""
    try:
        claim_id = str(uuid.uuid4())

        # Organization
        org_data = rc.get("organization") or {}
        org = Organization(
            name=org_data.get("name", "") or "",
            industry=org_data.get("industry", []) or [],
            employee_count=org_data.get("employee_count"),
        )

        # Problem
        prob_data = rc.get("problem") or {}
        problem = Problem(
            name=prob_data.get("name", "") or "",
            description=prob_data.get("description", "") or "",
            business_function=prob_data.get("business_function", []) or [],
        )

        # Intervention
        inv_data = rc.get("intervention") or {}
        try:
            inv_type = InterventionType(inv_data.get("intervention_type", "unknown"))
        except ValueError:
            inv_type = InterventionType.UNKNOWN
        intervention = Intervention(
            name=inv_data.get("name", "") or "",
            intervention_type=inv_type,
            vendors=inv_data.get("vendors", []) or [],
        )

        # Implementation
        impl_data = rc.get("implementation") or {}
        implementation = Implementation(
            duration_value=impl_data.get("duration_value"),
            duration_unit=impl_data.get("duration_unit", ""),
            scope=impl_data.get("scope", ""),
        )

        # Outcome / Metric
        out_data = rc.get("outcome") or {}
        metric_data = out_data.get("metric") or out_data
        try:
            mc = MetricCategory(metric_data.get("category", "other"))
        except ValueError:
            mc = MetricCategory.OTHER

        metric = Metric(
            name=metric_data.get("name", "") or "",
            category=mc,
            percentage_change=metric_data.get("percentage_change"),
            absolute_change=metric_data.get("absolute_change"),
            unit=metric_data.get("unit", ""),
            direction=OutcomeDirection.POSITIVE if metric_data.get("percentage_change", 0) or 0 > 0 else OutcomeDirection.NEUTRAL,
        )

        outcome = Outcome(
            metric=metric,
            summary=out_data.get("summary", "") or "",
        )

        # Evidence quality
        eq_data = rc.get("evidence_quality") or {}
        quality = EvidenceQuality(
            is_independent=eq_data.get("is_independent", False),
            is_vendor_reported=eq_data.get("is_vendor_reported", True),
            has_baseline=eq_data.get("has_baseline", False),
            sample_size=eq_data.get("sample_size"),
        )

        # Claim type
        ct_str = rc.get("claim_type", "problem")
        try:
            claim_type = ClaimType(ct_str)
        except ValueError:
            claim_type = ClaimType.PROBLEM

        excerpt = rc.get("supporting_excerpt", "") or ""
        locator = SourceLocator(text_excerpt=excerpt[:200])

        return EvidenceClaim(
            claim_id=claim_id,
            claim_type=claim_type,
            claim_text=rc.get("claim_text", "") or "",
            problem=problem,
            intervention=intervention,
            organization=org,
            implementation=implementation,
            outcome=outcome,
            metrics=[metric] if metric.name else [],
            source_document_id=document.document_id,
            source_url=document.source_url,
            source_locator=locator,
            supporting_excerpt=excerpt[:500],
            evidence_quality=quality,
            extraction_confidence=0.7,
            review_status=ReviewStatus.PENDING_REVIEW,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.warning(f"Failed to convert raw claim: {e}")
        return None
