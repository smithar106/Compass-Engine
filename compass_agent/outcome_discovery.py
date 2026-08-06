"""Outcome Discovery Worker — the refinery stage.

A specialized worker whose ONLY job is enriching implementations with the
decision-grade fields they're missing: deployment status, measurement
timeframe, sample size, and baseline. It deliberately does NOT re-rank,
re-classify, or touch evidence tier — the engine reclassifies on its own.

Why it exists: across the corpus, deployment status is captured in ~4% of
records, timeframe ~1%, sample size ~1%, baseline ~18%. Those four fields are
the difference between an implementation that is decision-grade today and one
that is stuck in the "supporting" bucket. Gold comes from recovering them, not
from re-ranking what already exists.

Flow per record:
  1. Skip records that already have all four fields (nothing to recover).
  2. Fetch the source document (same HttpFetcher the promotion pass uses).
  3. A single focused LLM call asks ONLY for the missing fields.
  4. Map recovered values onto engine enrichment fields and POST them.
  5. Engine reclassifies (evidence_level recomputed server-side).

Budget-gated per application and idempotent: a record that gained all four
fields leaves the candidate set. Records whose source genuinely lacks the
fields fail and are returned as failures so the daemon can cooldown them.
"""

from __future__ import annotations

import logging
from typing import Optional

from compass_agent.llm import LLMClient

log = logging.getLogger("compass_agent.outcome_discovery")

# The four decision-grade fields this worker recovers, with their llm keys.
TARGET_FIELDS = {
    "deployment_status": "deployment_status",
    "measurement_period": "measurement_period",
    "sample_size": "sample_size",
    "baseline": "baseline",
}

NON_DEPLOYED_STATUSES = {"unknown", "theoretical", "proposed"}

SYSTEM_PROMPT = (
    "You are an evidence-extraction specialist for an implementation "
    "intelligence library. Your ONLY job is to recover four fields from a "
    "source document about an AI/automation implementation:\n"
    "  - deployment_status: was it actually deployed/implemented in operations? "
    "One of: deployed, pilot, proposed, theoretical, unknown. "
    "'deployed' only when the text says it is live/in use/completed; 'pilot' "
    "when it was run as a pilot or proof-of-concept only.\n"
    "  - measurement_period: the period over which results were measured, as "
    "{\"value\": number, \"unit\": \"days|weeks|months|quarters|years\"}.\n"
    "  - sample_size: the number of transactions/records/units/users measured.\n"
    "  - baseline: the pre-implementation state the results were compared "
    "against, as a short quoted string.\n"
    "Return a JSON object with ONLY the keys you can support from the text. "
    "Set a key to null when the document does not state it. Do not invent "
    "numbers — if the period or sample is described only qualitatively "
    "(\"within weeks\", \"tens of thousands\"), encode what is defensible or "
    "null."
)


def _missing_fields(record: dict) -> list:
    """Which of the four target fields a record is missing."""
    missing = []

    status = str(record.get("result_status") or "").lower().strip()
    if status in NON_DEPLOYED_STATUSES or not status:
        missing.append("deployment_status")

    if not record.get("intervention_measurement_period_value"):
        missing.append("measurement_period")

    sample = record.get("sample_size")
    if sample is None or (isinstance(sample, (int, float)) and sample <= 1):
        missing.append("sample_size")

    if not record.get("has_baseline") and not record.get("problem_baseline_description"):
        missing.append("baseline")

    return missing


def _recovered_fields(missing: list, extraction: dict) -> dict:
    """Map a focused extraction onto engine enrichment ``fields``."""
    fields: dict = {}
    extraction = extraction or {}

    if "deployment_status" in missing:
        status = str(extraction.get("deployment_status") or "").lower().strip()
        if status in ("deployed", "pilot"):
            fields["result_status"] = status
        elif status in ("proposed", "theoretical"):
            fields["result_status"] = "proposed"

    if "measurement_period" in missing:
        period = extraction.get("measurement_period")
        if isinstance(period, dict):
            try:
                num = float(period.get("value"))
            except (TypeError, ValueError):
                num = None
            unit = str(period.get("unit") or "months").strip() or "months"
            if num is not None and num > 0:
                fields["intervention_measurement_period_value"] = num
                fields["intervention_measurement_period_unit"] = unit[:40]

    if "sample_size" in missing:
        value = extraction.get("sample_size")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > 1:
                fields["sample_size"] = int(value)
        elif isinstance(value, str):
            n = _first_number(value)
            if n is not None and n > 1:
                fields["sample_size"] = int(n)

    if "baseline" in missing:
        baseline = extraction.get("baseline")
        if isinstance(baseline, str) and baseline.strip():
            fields["has_baseline"] = True
            fields["problem_baseline_description"] = baseline.strip()[:800]

    return fields


def _first_number(value: str):
    import re

    m = re.search(r"(\d[\d,]*\.?\d*)", value or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _fetch_source(record: dict) -> str:
    """Fetch the source document text (mirrors promote._fetch_source)."""
    from compass_agent.discovery import HttpFetcher
    from compass_agent.promote import record_source_url

    url = record_source_url(record)
    if not url:
        return ""
    try:
        return HttpFetcher().fetch(url, record.get("intervention_title", ""))
    except Exception as exc:
        log.warning("source fetch failed for %s: %s", url, exc)
        return ""


def _post_enrichment(settings, record_id: str, fields: dict):
    """POST recovered fields to the engine enrichment endpoint (reclassify)."""
    import httpx

    if not fields:
        return 200, {"updated": 0}
    try:
        resp = httpx.post(
            f"{settings.compass_api_url.rstrip('/')}/api/evidence/enrichment",
            headers={"X-Compass-Agent-Key": settings.sync_token},
            json={
                "record_id": record_id,
                "fields": fields,
                "source": "compass_agent:outcome_discovery",
                "reclassify": True,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, resp.text[:200]
        return resp.status_code, resp.text[:200]
    except Exception as exc:
        return 0, str(exc)


def _build_prompt(record: dict, missing: list) -> str:
    from compass_agent.promote import record_source_url

    fields = ", ".join(missing)
    return (
        f"Source document URL: {record_source_url(record) or record.get('source_id') or ''}\n"
        f"Title: {record.get('intervention_title') or ''}\n"
        f"Organization: {record.get('organization_name') or ''}\n"
        f"The record currently lacks: {fields}.\n"
        "Extract ONLY these fields if the document supports them. Return JSON."
    )


def run_outcome_discovery(
    settings,
    budget,
    *,
    max_applications: int = 5,
    concurrency: int = 1,
    limit: int = 500,
    exclude_ids: Optional[set] = None,
) -> dict:
    """One discovery pass: recover decision-grade fields for the records most
    lacking them. Budget-gated and idempotent."""
    from compass_agent.daemon import BudgetTracker
    from compass_agent.promote import load_records_from_engine

    if not settings.provider_api_key_configured or not settings.sync_token or not settings.compass_api_url:
        return {"skipped": "no_api_key_or_token", "applied": 0, "recovered": 0, "candidates": 0}

    if budget is None:
        budget = BudgetTracker(
            max_daily=settings.max_daily_llm_usd,
            max_total=settings.max_total_llm_usd,
        )
    if not budget.can_work():
        return {"skipped": "budget", "applied": 0, "recovered": 0, "candidates": 0}

    records = load_records_from_engine(settings.compass_api_url, settings.sync_token, limit=limit)
    if not records:
        return {"skipped": "no_records", "applied": 0, "recovered": 0, "candidates": 0}

    exclude_ids = set(exclude_ids or set())

    # Rank: records missing the most fields (and thus gaining the most points)
    # first. Missing deployment is the single highest-value recovery (+2).
    ranked = []
    for rec in records:
        if rec.get("id") in exclude_ids:
            continue
        missing = _missing_fields(rec)
        if not missing:
            continue
        priority = (len(missing), "deployment_status" in missing, rec.get("id"))
        ranked.append((priority, rec, missing))
    ranked.sort(key=lambda x: x[0], reverse=True)

    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=max(1, concurrency),
    )
    applied = 0
    recovered_total = 0
    failures = []

    for _, record, missing in ranked[:max_applications]:
        if budget is not None and not budget.can_work():
            failures.append({"record_id": record.get("id"), "reason": "budget"})
            break

        text = _fetch_source(record)
        if len((text or "").strip()) < 80:
            failures.append({"record_id": record.get("id"), "reason": "no_source_text"})
            continue

        try:
            result = llm.enrich_focused(
                text,
                system=SYSTEM_PROMPT,
                user=_build_prompt(record, missing),
                title=record.get("intervention_title", ""),
                url=record.get("source_id", ""),
            )
        except Exception as exc:
            failures.append({"record_id": record.get("id"), "reason": f"llm_error: {exc}"})
            continue

        if budget is not None and result.cost > 0:
            budget.spend(result.cost)

        extraction = result.payload if isinstance(result.payload, dict) else {}
        if extraction.get("no_fields"):
            failures.append({"record_id": record.get("id"), "reason": "no_fields_recovered"})
            continue

        fields = _recovered_fields(missing, extraction)
        if not fields:
            failures.append({"record_id": record.get("id"), "reason": "no_fields_recovered"})
            continue

        status, resp = _post_enrichment(settings, record.get("id"), fields)
        if status == 200:
            applied += 1
            recovered_total += len(fields)
        else:
            failures.append({"record_id": record.get("id"), "reason": f"http_{status}: {resp}"})

    return {
        "candidates": len(ranked),
        "applied": applied,
        "recovered": recovered_total,
        "failed": len(failures),
        "failures": failures[:10],
        "daily_spent": round(budget.daily_spent, 6) if budget is not None else 0.0,
    }


__all__ = [
    "run_outcome_discovery",
    "_missing_fields",
    "_recovered_fields",
    "TARGET_FIELDS",
    "SYSTEM_PROMPT",
]
