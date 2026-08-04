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

DEFAULT_DISCOVER_PER_CYCLE = 200


def backfill_collector_db(db_path: str) -> int:
    """Add the canonical organization backfill (organization_normalized) to the
    agent's collector DB so matching + eval use canonical industries. The engine
    backfill runs on the engine volume; the agent's own DB needs it too.
    Idempotent; returns the number of records normalized."""
    import json
    from types import SimpleNamespace as NS

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return 0
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(intervention_records)")}
        if "organization_normalized" not in cols:
            conn.execute("ALTER TABLE intervention_records ADD COLUMN organization_normalized TEXT")

        from compass_collector.organization.backfill import normalize_record

        rows = conn.execute(
            "SELECT id, organization_name, organization_industry, problem_statement,"
            " organization_employee_count, organization_geography, problem_business_function"
            " FROM intervention_records"
        ).fetchall()
        updated = 0
        for row in rows:
            industry = row[2]
            if isinstance(industry, str):
                try:
                    industry = json.loads(industry)
                except Exception:
                    industry = [industry]
            geography = row[5]
            if isinstance(geography, str):
                try:
                    geography = json.loads(geography)
                except Exception:
                    geography = []
            rec = NS(
                id=row[0],
                organization_name=row[1],
                organization_industry=industry or [],
                problem_statement=row[3] or "",
                organization_employee_count=row[4],
                organization_geography=geography or [],
                problem_business_function=row[6] or [],
            )
            try:
                payload = normalize_record(rec)
            except Exception:
                continue
            conn.execute(
                "UPDATE intervention_records SET organization_normalized = ? WHERE id = ?",
                (json.dumps(payload), row[0]),
            )
            updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


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
        # Resilient to schema drift: some collector copies lack the backfilled
        # organization_normalized column (e.g. the agent's own downloaded DB).
        cols = {row[1] for row in conn.execute("PRAGMA table_info(intervention_records)")}
        has_norm = "organization_normalized" in cols
        has_families = "intervention_families" in cols
        base_cols = ("id", "organization_name", "intervention_components",
                     "problem_business_function", "evidence_level",
                     "rollout_strategy", "success_criteria", "lessons_learned",
                     "implementation_pattern", "result_status")
        select_cols = list(base_cols)
        if has_norm:
            select_cols.append("organization_normalized")
        if has_families:
            select_cols.append("intervention_families")
        sql = f"SELECT {', '.join(select_cols)} FROM intervention_records"
        if limit:
            sql += " LIMIT ?"
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
            norm = r["organization_normalized"] if has_norm else {}
            if isinstance(norm, str):
                import json as _json

                try:
                    norm = _json.loads(norm)
                except Exception:
                    norm = {}
            records.append(
                NS(
                    id=r["id"],
                    organization_name=r["organization_name"] or "",
                    organization_normalized=norm if isinstance(norm, dict) else {},
                    intervention_components=comps if isinstance(comps, dict) else {},
                    problem_business_function=r["problem_business_function"] or [],
                    evidence_level=r["evidence_level"] or "",
                    rollout_strategy=r["rollout_strategy"] or "",
                    success_criteria=r["success_criteria"] or [],
                    lessons_learned=r["lessons_learned"] or [],
                    implementation_pattern=r["implementation_pattern"] or [],
                    intervention_families=r["intervention_families"] if has_families else [],
                    result_status=r["result_status"] or "",
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
    """Run one Inspect→Plan→Discover pass.

    DDG search runs first every cycle (130 ROI queries). Source Libraries are
    a secondary pass — only if budget remains and the library hasn't been
    crawled recently.
    """
    from compass_agent.campaign import Campaign, CampaignPlanner
    from compass_agent.libraries import ensure_libraries, prioritize_libraries, run_library

    records = load_records(collector_db)
    if not records:
        return {"planned": 0, "campaign": None, "discovered": 0, "accepted": 0, "rejected": 0}

    gaps = analyze_gaps(records)

    active = store.list_campaigns(status="active")
    if not active:
        planned = CampaignPlanner(store, min_impact=min_impact).plan(gaps)
        if not planned:
            return {"planned": 0, "campaign": None, "discovered": 0, "accepted": 0, "rejected": 0}
        store.update_campaign(planned[0].id, status="active")
        campaign = planned[0]
    else:
        campaign = Campaign(**active[0])

    result = {"campaign": campaign.id, "workflow": campaign.workflow,
              "discovered": 0, "accepted": 0, "rejected": 0, "cost_usd": 0.0, "source": "none"}

    # 1) DDG search first — high-volume discovery from 130 ROI queries.
    #    Runs every cycle. Libraries are secondary.
    try:
        report = discovery.run(campaign, max_sources=max_sources)
    except Exception as exc:
        log.warning("discovery run failed: %s", exc)
        report = None
    if report is not None:
        result.update({
            "discovered": report.sources_discovered,
            "accepted": report.accepted,
            "rejected": report.rejected,
            "cost_usd": round(report.cost_usd, 6),
            "source": "ddg_search",
        })
        campaign.discovered += report.sources_discovered
        campaign.accepted += report.accepted
        campaign.rejected += report.rejected
        campaign.cost_usd += report.cost_usd

    # 2) Source Library — secondary pass, only if budget allows.
    ensure_libraries(store)
    libraries = prioritize_libraries(store)
    if libraries:
        try:
            lib_result = run_library(
                store, libraries[0], discovery, campaign,
                max_pages=min(max_sources // 2, 10),
            )
        except Exception as exc:
            log.warning("library crawl failed for %s: %s", libraries[0]["id"], exc)
            lib_result = None
        if lib_result and lib_result["accepted"] > 0:
            campaign.discovered += lib_result["pages_processed"]
            campaign.accepted += lib_result["accepted"]
            campaign.rejected += lib_result["rejected"]
            campaign.cost_usd += lib_result["cost_usd"]
            result["discovered"] += lib_result["pages_processed"]
            result["accepted"] += lib_result["accepted"]
            result["rejected"] += lib_result["rejected"]
            result["cost_usd"] = round(result["cost_usd"] + lib_result["cost_usd"], 6)
            if not result["source"].startswith("ddg"):
                result["source"] = f"library:{libraries[0]['id']}"
            else:
                result["source"] += f"+library:{libraries[0]['id']}"

    store.update_campaign(
        campaign.id,
        discovered=campaign.discovered,
        accepted=campaign.accepted,
        rejected=campaign.rejected,
        rich_records_created=campaign.rich_records_created,
        cost_usd=campaign.cost_usd,
    )
    result["planned"] = 1
    return result
