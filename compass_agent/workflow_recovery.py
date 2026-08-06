"""Workflow Recovery Worker — the LLM refinery stage for workflows.

Deterministic keyword inference (``workflow_taxonomy.infer_workflow``) has a
ceiling: records whose title/problem statement carry no workflow signal
(typically generic vendor-blog titles) stay ``uncategorized``. This worker
recovers their primary operational workflow from the **source document body**
with a single focused LLM call, then maps the recovered phrase onto the
canonical ``ALL_WORKFLOWS`` taxonomy.

Flow per record:
  1. Skip records whose canonical workflow is already known (confidence >= 0.5).
  2. Fetch the source text — document body (``cleaned_text``) first, HTTP fetch
     of the recorded source URL as fallback.
  3. One focused LLM call asks ONLY for the single primary workflow.
  4. Map the recovered phrase onto the canonical slug via
     ``normalize_workflow``; phrases that don't map are returned as
     **taxonomy candidates** so the alias/keyword table can be extended.
  5. Write ``workflow_normalized`` with ``source="llm_recovery"``.

Budget-gated and idempotent: recovered records leave the candidate set.
Dry-run prints the prompts without calling the LLM.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from compass_collector.organization.backfill import _as_list
from compass_collector.organization.workflow_taxonomy import (
    WORKFLOW_NORMALIZATION_VERSION,
    normalize_workflow,
    workflow_function,
)

log = logging.getLogger("compass_agent.workflow_recovery")

MIN_KNOWN_CONFIDENCE = 0.5   # below this, the workflow is not yet trustworthy
RECOVERED_CONFIDENCE = 0.85  # LLM + canonical mapping
UNMAPPED_SOURCE = "llm_recovery_unmapped"  # processed once, never re-hunted
NO_SOURCE_SOURCE = "no_source"              # unresolvable via this worker

SYSTEM_PROMPT = (
    "You are an evidence-extraction specialist for an implementation "
    "intelligence library. Your ONLY job is to identify the SINGLE primary "
    "operational workflow an organization automated or transformed in the "
    "source document.\n"
    "Rules:\n"
    "  - Output the workflow as a short verb+object phrase, e.g. "
    "'invoice processing', 'customer service call handling', 'contract "
    "review', 'warehouse management', 'employee onboarding'.\n"
    "  - Choose the workflow the document is MOST about — the one with the "
    "described intervention and measured outcome.\n"
    "  - If the document describes no operational workflow (pure marketing, "
    "research announcement, product launch), return {\"workflow\": null}.\n"
    "Return a JSON object with exactly one key: {\"workflow\": \"...\"} or "
    "{\"workflow\": null}. Do not include any other text."
)


def _candidate(rec: Any) -> bool:
    """True when the record's canonical workflow is not yet trustworthy.

    Records already processed by the recovery worker — mapped OR unmapped —
    are excluded so repeated passes do not re-burn LLM budget on them.
    """
    wn = getattr(rec, "workflow_normalized", None) or {}
    if not isinstance(wn, dict) or not wn.get("value"):
        return True
    if wn.get("source") in ("llm_recovery", UNMAPPED_SOURCE):
        return False
    try:
        return float(wn.get("confidence", 0)) < MIN_KNOWN_CONFIDENCE
    except (TypeError, ValueError):
        return True


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


def _source_text(session, rec: Any) -> str:
    """Document body first (already fetched), HTTP fetch as fallback."""
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


def _build_prompt(rec: Any) -> str:
    comps = getattr(rec, "intervention_components", None) or {}
    url = str(comps.get("source_url") or "") if isinstance(comps, dict) else ""
    return (
        f"Source document URL: {url or getattr(rec, 'source_id', '') or ''}\n"
        f"Title: {getattr(rec, 'intervention_title', '') or ''}\n"
        f"Organization: {getattr(rec, 'organization_name', '') or ''}\n"
        "Identify the single primary operational workflow."
    )


def _map_recovered(phrase: Optional[str]) -> Optional[dict]:
    """Map an LLM-recovered workflow phrase onto the canonical taxonomy.

    Returns the ``workflow_normalized`` payload when the phrase maps at
    confidence >= 0.6, else None (caller records it as a taxonomy candidate).
    """
    if not phrase or not str(phrase).strip():
        return None
    nv = normalize_workflow(str(phrase).strip())
    if nv.confidence < 0.6 or not nv.value:
        return None
    entry = {
        "raw": nv.raw or str(phrase).strip(),
        "value": nv.value,
        "source": "llm_recovery",
        "method": "explicit",
        "confidence": RECOVERED_CONFIDENCE,
        "version": WORKFLOW_NORMALIZATION_VERSION,
    }
    fn = workflow_function(nv.value)
    if fn:
        entry["function"] = fn
    return entry


def run_workflow_recovery(
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
    """One recovery pass over records with unknown workflows.

    ``llm`` — injectable callable ``(text, system, user, title, url) -> obj
    with .payload dict and .cost float`` (defaults to LLMClient.enrich_focused).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from compass_collector.database import Base
    from compass_collector.models.intervention import InterventionRecord

    if not dry_run and not api_key:
        return {"skipped": "no_api_key", "candidates": 0, "recovered": 0, "unmapped": 0, "applied": 0}
    if budget is not None and not budget.can_work():
        return {"skipped": "budget", "candidates": 0, "recovered": 0, "unmapped": 0, "applied": 0}

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
        unmapped = 0
        applied = 0
        failed = 0
        cost = 0.0
        taxonomy_candidates: list[str] = []
        from collections import Counter

        top_workflows: Counter = Counter()

        for rec in candidates:
            if budget is not None and not budget.can_work():
                failed += 1
                break
            text = _source_text(session, rec)
            if len((text or "").strip()) < 80:
                failed += 1
                if not dry_run:
                    rec.workflow_normalized = {
                        "raw": "", "value": "uncategorized", "source": NO_SOURCE_SOURCE,
                        "method": "skipped", "confidence": 0.0,
                        "version": WORKFLOW_NORMALIZATION_VERSION,
                    }
                continue

            if dry_run:
                print(f"[dry-run] {getattr(rec, 'id', '?')} :: {getattr(rec, 'intervention_title', '') or ''}")
                print(_build_prompt(rec))
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
            phrase = payload.get("workflow") if isinstance(payload, dict) else None
            entry = _map_recovered(phrase)
            if entry:
                rec.workflow_normalized = entry
                applied += 1
                recovered += 1
                top_workflows[entry["value"]] += 1
            else:
                # Processed but unmappable — record it once so later passes
                # don't re-burn budget on the same record.
                if phrase and str(phrase).strip():
                    unmapped += 1
                    taxonomy_candidates.append(str(phrase).strip()[:80])
                else:
                    failed += 1
                if not dry_run:
                    rec.workflow_normalized = {
                        "raw": str(phrase or "").strip()[:200],
                        "value": "uncategorized",
                        "source": UNMAPPED_SOURCE,
                        "method": "unmapped",
                        "confidence": 0.0,
                        "version": WORKFLOW_NORMALIZATION_VERSION,
                    }

        if not dry_run:
            session.commit()
    finally:
        session.close()

    return {
        "dry_run": dry_run,
        "candidates": len(candidates),
        "applied": applied,
        "recovered": recovered,
        "unmapped": unmapped,
        "failed": failed,
        "cost_usd": round(cost, 6),
        "top_workflows": top_workflows.most_common(15),
        "taxonomy_candidates": sorted(set(taxonomy_candidates))[:20],
    }


__all__ = [
    "run_workflow_recovery",
    "_candidate",
    "_map_recovered",
    "_source_text",
    "SYSTEM_PROMPT",
    "MIN_KNOWN_CONFIDENCE",
]
