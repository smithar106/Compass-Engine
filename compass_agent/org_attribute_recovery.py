"""Org Attribute Recovery Worker — LLM refinery for geography + company size.

Deterministic extraction (backfill regex) recovered geography in ~3.4% and
employee count in ~0.8% of records — the two attributes that make
implementation diversity (countries, company-size bands) computable. This
worker recovers them from the source document body with one focused LLM call
per record.

Flow per record:
  1. Skip records whose geography AND employee count are already known.
  2. Fetch the source text — document body first, HTTP fetch fallback.
  3. One LLM call asks ONLY for geography + employee count.
  4. Write the recovered values into ``organization_normalized`` (merged,
     provenance attached: source="llm_recovery"), including the derived
     employee band.
  5. Budget-gated, idempotent, dry-run, injectable LLM for tests.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from compass_collector.organization.backfill import _as_list
from compass_collector.organization.taxonomy import (
    NORMALIZATION_VERSION,
    employee_count_to_band,
    normalize_geography,
)

log = logging.getLogger("compass_agent.org_attribute_recovery")

RECOVERED_CONFIDENCE = 0.7  # LLM + post-processing

SYSTEM_PROMPT = (
    "You are an evidence-extraction specialist for an implementation "
    "intelligence library. Your ONLY job is to recover two organization "
    "attributes from a source document:\n"
    "  - geography: the country (or region, if only a region is named) where "
    "the implementing organization is based, e.g. 'United States', 'Germany', "
    "'Europe'. Use the country when the document states it.\n"
    "  - employee_count: the organization's total number of employees, as an "
    "integer, when the document states it. Do NOT use the number of "
    "transactions/units/users processed by the implementation.\n"
    "Return a JSON object with exactly these keys, setting each to null when "
    "the document does not support it: {\"geography\": \"...\" or null, "
    "\"employee_count\": 1234 or null}. Do not invent values."
)


def _candidate(rec: Any) -> bool:
    """True when either geography or employee count is missing/untrusted."""
    norm = getattr(rec, "organization_normalized", None) or {}
    if not isinstance(norm, dict):
        return True

    def known(key: str) -> bool:
        entry = norm.get(key)
        if not isinstance(entry, dict) or not entry.get("value"):
            return False
        try:
            return float(entry.get("confidence", 0)) >= 0.5
        except (TypeError, ValueError):
            return False

    return not (known("geography") and known("employee_count"))


def _source_text(session, rec: Any) -> str:
    doc_id = getattr(rec, "document_id", None)
    if doc_id:
        try:
            from compass_collector.models.document import Document

            doc = session.get(Document, doc_id)
            if doc and doc.cleaned_text and len(str(doc.cleaned_text).strip()) >= 80:
                return str(doc.cleaned_text)
        except Exception as exc:  # noqa: BLE001
            log.warning("document body read failed for %s: %s", doc_id, exc)
    comps = getattr(rec, "intervention_components", None) or {}
    url = ""
    if isinstance(comps, dict):
        url = str(comps.get("source_url") or "").strip()
    if url.startswith(("http://", "https://")):
        try:
            from compass_agent.discovery import HttpFetcher

            return HttpFetcher().fetch(url, getattr(rec, "intervention_title", "") or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("source fetch failed for %s: %s", url, exc)
    return ""


def _source_rank(session, rec: Any) -> int:
    """Cheapest-to-process candidates first: 2=doc body, 1=http url, 0=none."""
    doc_id = getattr(rec, "document_id", None)
    if doc_id:
        try:
            from compass_collector.models.document import Document

            doc = session.get(Document, doc_id)
            if doc and doc.cleaned_text and len(str(doc.cleaned_text).strip()) >= 80:
                return 2
        except Exception:  # noqa: BLE001
            pass
    comps = getattr(rec, "intervention_components", None) or {}
    if isinstance(comps, dict) and str(comps.get("source_url") or "").startswith(("http://", "https://")):
        return 1
    return 0


def _build_prompt(rec: Any) -> str:
    comps = getattr(rec, "intervention_components", None) or {}
    url = str(comps.get("source_url") or "") if isinstance(comps, dict) else ""
    return (
        f"Source document URL: {url or getattr(rec, 'source_id', '') or ''}\n"
        f"Title: {getattr(rec, 'intervention_title', '') or ''}\n"
        f"Organization: {getattr(rec, 'organization_name', '') or ''}\n"
        "Recover geography and employee_count ONLY if the document supports them."
    )


def _map_recovered(payload: Optional[dict]) -> dict:
    """Map LLM output onto organization_normalized entries (merged later)."""
    entries: dict[str, dict] = {}
    if not isinstance(payload, dict):
        return entries

    geo_raw = str(payload.get("geography") or "").strip()
    if geo_raw and len(geo_raw) >= 2:
        nv = normalize_geography(geo_raw)
        entries["geography"] = {
            "raw": nv.raw or geo_raw,
            "value": nv.value or geo_raw,
            "source": "llm_recovery",
            "method": "explicit",
            "confidence": RECOVERED_CONFIDENCE,
            "version": NORMALIZATION_VERSION,
        }

    emp_raw = payload.get("employee_count")
    if emp_raw is not None:
        try:
            count = int(float(str(emp_raw).replace(",", "").strip()))
            if count > 0:
                band = employee_count_to_band(count)
                entries["employee_count"] = {
                    "raw": str(emp_raw),
                    "value": str(count),
                    "source": "llm_recovery",
                    "method": "explicit",
                    "confidence": RECOVERED_CONFIDENCE,
                    "version": NORMALIZATION_VERSION,
                }
                if band:
                    entries["employee_band"] = {
                        "raw": str(count),
                        "value": band,
                        "source": "llm_recovery",
                        "method": "inferred",
                        "confidence": RECOVERED_CONFIDENCE,
                        "version": NORMALIZATION_VERSION,
                    }
        except (TypeError, ValueError):
            pass
    return entries


def run_org_attribute_recovery(
    db_path: str,
    *,
    api_key: str = "",
    provider: str = "deepseek",
    max_applications: int = 5,
    concurrency: int = 1,
    limit: int = 500,
    dry_run: bool = False,
    budget=None,
    llm: Optional[Callable] = None,
) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from compass_collector.database import Base
    from compass_collector.models.intervention import InterventionRecord

    if not dry_run and not api_key:
        return {"skipped": "no_api_key", "candidates": 0, "recovered": 0, "applied": 0}
    if budget is not None and not budget.can_work():
        return {"skipped": "budget", "candidates": 0, "recovered": 0, "applied": 0}

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        records = session.query(InterventionRecord).limit(limit).all()
        candidates = [r for r in records if _candidate(r)]
        candidates.sort(key=lambda r: _source_rank(session, r), reverse=True)
        candidates = candidates[:max_applications]

        client = None
        if llm is None and not dry_run:
            from compass_agent.llm import LLMClient

            client = LLMClient(api_key=api_key, provider=provider, concurrency=max(1, concurrency))

        def _call(text, system, user, title, url):
            if llm is not None:
                return llm(text, system, user, title, url)
            assert client is not None
            return client.enrich_focused(text, system=system, user=user, title=title, url=url)

        recovered = 0
        applied = 0
        failed = 0
        cost = 0.0
        geo_recovered = 0
        emp_recovered = 0

        for rec in candidates:
            if budget is not None and not budget.can_work():
                failed += 1
                break
            text = _source_text(session, rec)
            if len((text or "").strip()) < 80:
                failed += 1
                continue

            if dry_run:
                print(f"[dry-run] {getattr(rec, 'id', '?')} :: {getattr(rec, 'organization_name', '') or ''} — {getattr(rec, 'intervention_title', '') or ''}")
                continue

            try:
                result = _call(text, SYSTEM_PROMPT, _build_prompt(rec),
                               getattr(rec, "intervention_title", "") or "",
                               (getattr(rec, "intervention_components", {}) or {}).get("source_url", ""))
            except Exception as exc:  # noqa: BLE001
                log.warning("llm call failed for %s: %s", getattr(rec, "id", "?"), exc)
                failed += 1
                continue
            if budget is not None:
                budget.spend(result.cost)
            cost += float(getattr(result, "cost", 0) or 0)

            payload = getattr(result, "payload", None) or {}
            entries = _map_recovered(payload if isinstance(payload, dict) else {})
            if not entries:
                failed += 1
                continue

            norm = dict(getattr(rec, "organization_normalized", None) or {})
            norm.update(entries)
            rec.organization_normalized = norm
            applied += 1
            recovered += len(entries)
            if "geography" in entries:
                geo_recovered += 1
            if "employee_count" in entries:
                emp_recovered += 1

        if not dry_run:
            session.commit()
    finally:
        session.close()

    return {
        "dry_run": dry_run,
        "candidates": len(candidates),
        "applied": applied,
        "recovered": recovered,
        "geography_recovered": geo_recovered,
        "employee_count_recovered": emp_recovered,
        "failed": failed,
        "cost_usd": round(cost, 6),
    }


__all__ = [
    "run_org_attribute_recovery",
    "_candidate",
    "_map_recovered",
    "_source_text",
    "SYSTEM_PROMPT",
    "RECOVERED_CONFIDENCE",
]
