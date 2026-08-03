"""Evidence Operations cycle orchestration.

Inspect → Plan → Discover, wired into the daemon cycle alongside enrichment.

Inspect: gap analysis over the collector DB (which decision categories have the
largest evidence gaps). Plan: persist a ranked Campaign when none is active.
Discover: run DiscoveryPipeline for the active campaign, budget-gated, and fold
the results (accepted/rejected/cost) back into the campaign.
"""

from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace as NS
from typing import Optional

from compass_agent.campaign import Campaign, CampaignPlanner
from compass_agent.gap_analysis import analyze_gaps
from compass_agent.store import AgentStore

log = logging.getLogger("compass_agent.evidence_ops")

DEFAULT_DISCOVER_PER_CYCLE = 3


def load_records(db_path: str, limit: Optional[int] = None) -> list:
    """Load collector-DB records as lightweight objects for gap analysis."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("SELECT COUNT(*) FROM intervention_records")
        except sqlite3.Error:
            return []
        sql = (
            "SELECT id, intervention_components, problem_business_function,"
            " evidence_level, rollout_strategy, success_criteria, lessons_learned,"
            " implementation_pattern FROM intervention_records"
            " LIMIT ?" if limit else
            "SELECT id, intervention_components, problem_business_function,"
            " evidence_level, rollout_strategy, success_criteria, lessons_learned,"
            " implementation_pattern FROM intervention_records"
        )
        params = (limit,) if limit else ()
        rows = conn.execute(sql, params).fetchall()
        records = []
        for r in rows:
            comps = r["intervention_components"]
            if isinstance(comps, str):
                import json as _json

                try:
                    comps = _json.loads(comps)
                except Exception:
                    comps = {}
            records.append(
                NS(
                    id=r["id"],
                    intervention_components=comps if isinstance(comps, dict) else {},
                    problem_business_function=r["problem_business_function"] or [],
                    evidence_level=r["evidence_level"] or "",
                    rollout_strategy=r["rollout_strategy"] or "",
                    success_criteria=r["success_criteria"] or [],
                    lessons_learned=r["lessons_learned"] or [],
                    implementation_pattern=r["implementation_pattern"] or [],
                )
            )
        return records
    finally:
        conn.close()


def run_evidence_ops(
    store: AgentStore,
    collector_db: str,
    discovery,
    max_sources: int = DEFAULT_DISCOVER_PER_CYCLE,
    min_impact: float = 0.1,
) -> dict:
    """Run one Inspect→Plan→Discover pass. Returns a summary dict."""
    records = load_records(collector_db)
    if not records:
        return {"planned": 0, "campaign": None, "discovered": 0, "accepted": 0, "rejected": 0}

    gaps = analyze_gaps(records)

    active = store.list_campaigns(status="active")
    if not active:
        planned = CampaignPlanner(store, min_impact=min_impact).plan(gaps)
        if not planned:
            return {"planned": 0, "campaign": None, "discovered": 0, "accepted": 0, "rejected": 0}
        # activate the single highest-impact campaign
        store.update_campaign(planned[0].id, status="active")
        campaign = planned[0]
    else:
        campaign = Campaign(**active[0])

    report = discovery.run(campaign, max_sources=max_sources)

    store.update_campaign(
        campaign.id,
        discovered=campaign.discovered,
        accepted=campaign.accepted,
        rejected=campaign.rejected,
        rich_records_created=campaign.rich_records_created,
        cost_usd=campaign.cost_usd,
    )
    return {
        "planned": 1 if active and not active else 1,
        "campaign": campaign.id,
        "workflow": campaign.workflow,
        "discovered": report.sources_discovered,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "cost_usd": round(report.cost_usd, 6),
        "rejections": report.rejections,
    }
