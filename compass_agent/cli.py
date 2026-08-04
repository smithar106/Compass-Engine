"""Command-line interface for the Compass Evidence Agent.

Commands::

    python -m compass_agent --help
    python -m compass_agent status
    python -m compass_agent daemon
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from compass_agent import __version__
from compass_agent.config import Settings, load_settings
from compass_agent.daemon import Daemon, check_engine_health, print_startup_summary

log = logging.getLogger("compass_agent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m compass_agent",
        description="Compass Evidence Agent — keeps the evidence pipeline alive "
        "and budget-controlled on Railway.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("status", help="Show configuration, engine connectivity, and status")
    sub.add_parser("daemon", help="Run the worker loop (Railway start command)")
    bench = sub.add_parser(
        "benchmark", help="Run the enrichment gold-set benchmark and print a report"
    )
    bench.add_argument(
        "--gold-set", action="store_true",
        help="Run against the built-in gold set (requires an LLM API key)",
    )
    bench.add_argument(
        "--dry-run", action="store_true",
        help="Run against the built-in gold set with a deterministic reference extractor (no LLM)",
    )
    sub.add_parser("metrics", help="Print enrichment cost/rejection/richness metrics from the agent store")
    camp = sub.add_parser("campaign", help="Evidence Operations: inspect gaps, plan/run targeted evidence campaigns")
    camp.add_argument("action", choices=["plan", "list", "run", "archive"], help="campaign action")
    camp.add_argument("--sources", type=int, default=3, help="max sources to discover per run")
    lib = sub.add_parser("libraries", help="Source Library dashboard: health, crawl, and prioritization")
    lib.add_argument("action", choices=["status", "crawl", "rank"], help="library action")
    lib.add_argument("--library", type=str, default="", help="library id to crawl")
    lib.add_argument("--pages", type=int, default=5, help="max pages per library crawl")
    roi = sub.add_parser(
        "roi-search",
        help="Run mass Google search for 1000+ ROI case studies across all "
        "industries and intervention types. Uses OpenCLI google search adapter."
    )
    roi.add_argument("--queries", type=int, default=50, help="max queries to run (default 50, covers ~2500 results)")
    roi.add_argument("--limit", type=int, default=50, help="results per query (default 50, max 100)")
    roi.add_argument("--dry-run", action="store_true", help="show queries without executing")
    ev = sub.add_parser("eval", help="Retrieval evaluation: recall, sensitivity, weight stability")
    ev.add_argument("action", choices=["retrieval", "sensitivity"], help="eval action")
    return parser


def _print_config_errors(problems: list[str]) -> int:
    print("Compass Evidence Agent", flush=True)
    print("Status: configuration error", flush=True)
    for problem in problems:
        print(f"  - {problem}", flush=True)
    return 1


def _build_enrichment_workflow(settings: Settings, budget):
    """Build the budget-controlled enrichment pipeline, or None when it cannot run."""
    from compass_agent.claim import ClaimQueue, CollectorCandidateProvider
    from compass_agent.daemon import BudgetTracker
    from compass_agent.db import ensure_collector_db
    from compass_agent.enrich import EnrichmentPipeline
    from compass_agent.llm import LLMClient
    from compass_agent.publish import HttpPublisher, NoopPublisher, Publisher
    from compass_agent.store import AgentStore
    from compass_agent.workflow import EnrichmentWorkflow

    if not settings.provider_api_key_configured:
        return None

    # Resolve a real collector DB (downloads it when missing / a git-lfs pointer).
    db_path = ensure_collector_db(path=settings.candidate_db, allow_download=settings.auto_download_db)
    if not db_path:
        log.warning("Enrichment inactive: no valid collector DB (AGENT_CANDIDATE_DB).")
        return None

    # Persistent claim/enrichment store (AGENT_STORE_DB), in-memory otherwise.
    store = AgentStore(db_path=settings.store_db or "")
    provider = CollectorCandidateProvider(db_path=db_path)
    queue = ClaimQueue(provider=provider, store=store)
    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=settings.llm_concurrency,
    )
    # Publish path: HTTP sync to the engine when configured, otherwise local
    # SQLite write, otherwise no-op (results still recorded in the store).
    if settings.auto_publish and settings.sync_token:
        publisher = HttpPublisher(
            api_url=settings.compass_api_url,
            token=settings.sync_token,
            enabled=True,
        )
        log.info("Enrichment publishing via engine HTTP sync (%s/api/evidence/enrichment)", settings.compass_api_url)
    elif settings.auto_publish:
        publisher = Publisher(db_path=db_path, enabled=True)
        log.info("Enrichment publishing locally to %s", db_path)
    else:
        publisher = NoopPublisher()
    workflow = EnrichmentWorkflow(
        queue=queue,
        pipeline=EnrichmentPipeline(llm),
        store=store,
        budget=budget,
        publisher=publisher,
        concurrency=settings.llm_concurrency,
        auto_publish=settings.auto_publish,
        model=llm.model,
    )
    return workflow


def cmd_status(settings: Settings, problems: list[str]) -> int:
    if problems:
        return _print_config_errors(problems)
    ok, detail = check_engine_health(settings.compass_api_url)
    print_startup_summary(settings, mode="status", engine_ok=ok, engine_detail=detail)
    return 0


def _build_discovery(settings: Settings, store, collector_db: str):
    """Build the Discovery Mode pipeline, or None when it cannot run."""
    from compass_agent.discovery import (
        CuratedSeedSearch,
        DiscoveryPipeline,
        DuckDuckGoSearch,
        GoogleSearch,
        HttpFetcher,
        IngestPublisher,
        OpenCLISearch,
        SourcePlanner,
    )
    from compass_agent.llm import LLMClient

    if not settings.provider_api_key_configured or not collector_db:
        return None
    if not settings.sync_token:
        log.warning("Discovery inactive: AGENT_SYNC_TOKEN not set.")
        return None
    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=1,
    )
    return DiscoveryPipeline(
        planner=SourcePlanner(
            # priority order: Google Search first (highest yield for business ROI
            # case studies with real outcomes), then DuckDuckGo + curated seeds,
            # then OpenCLI for community/academic results
            backends=[GoogleSearch(), DuckDuckGoSearch(), CuratedSeedSearch(), OpenCLISearch()],
            max_per_query=25,
        ),
        fetcher=HttpFetcher(),
        llm=llm,
        ingest=IngestPublisher(
            api_url=settings.compass_api_url,
            token=settings.sync_token,
            enabled=True,
        ),
    )


def cmd_daemon(settings: Settings, problems: list[str]) -> int:
    if problems:
        return _print_config_errors(problems)

    if not settings.provider_api_key_configured:
        key_env = settings.missing_provider_key_env or "provider API key"
        print(
            f"WARNING: {key_env} is not set — LLM operations will be paused "
            "until configured. The worker stays alive for connectivity and budget.",
            flush=True,
        )

    from compass_agent.daemon import BudgetTracker

    budget = BudgetTracker(
        max_daily=settings.max_daily_llm_usd,
        max_total=settings.max_total_llm_usd,
        state_file=settings.state_file,
    )
    # Resolve a real collector DB for gap analysis + discovery candidates.
    from compass_agent.db import ensure_collector_db
    from compass_agent.evidence_ops import backfill_collector_db
    from compass_agent.store import AgentStore

    collector_db = ensure_collector_db(path=settings.candidate_db, allow_download=settings.auto_download_db)
    if collector_db:
        try:
            from compass_agent.evidence_ops import backfill_collector_db
            backfill_collector_db(collector_db)
        except Exception:
            pass
    if collector_db:
        try:
            n = backfill_collector_db(collector_db)
            if n:
                log.info("Backfilled %d records on the agent collector DB (organization_normalized)", n)
        except Exception as exc:
            log.warning("collector DB backfill failed (non-fatal): %s", exc)
    store = AgentStore(db_path=settings.store_db or "")
    enrichment = _build_enrichment_workflow(settings, budget)
    discovery = _build_discovery(settings, store, collector_db)
    if enrichment is None and discovery is None:
        print("NOTE: enrichment + discovery inactive (no API key / candidate DB / sync token).", flush=True)
    daemon = Daemon(
        settings,
        budget=budget,
        enrichment=enrichment,
        discovery=discovery,
        collector_db=collector_db,
        store=store,
    )
    return daemon.run()


def cmd_benchmark(settings: Settings, problems: list[str], dry_run: bool, gold_set: bool) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.benchmark import GOLD_SET, print_benchmark_report, run_benchmark
    from compass_agent.store import AgentStore

    store = AgentStore(db_path=settings.store_db or "")

    def reference_extractor(text: str, title: str) -> dict:
        # Deterministic extractor used for --dry-run and tests (no LLM).
        lower = text.lower()
        payload = {
            "organization_name": "",
            "intervention_category": "",
            "evidence_tier": "silver",
            "workflow": "",
            "intervention_title": "",
        }
        if "shopify" in lower:
            payload["organization_name"] = "Shopify"
            payload["intervention_category"] = "Software"
            payload["workflow"] = "commerce processing"
            payload["intervention_title"] = "Cloud migration"
        if "chatbot" in lower or "support" in lower:
            payload["organization_name"] = "regional bank"
            payload["intervention_category"] = "AI"
            payload["workflow"] = "customer support"
            payload["intervention_title"] = "AI support chatbot"
        if "migrated" in lower:
            payload["evidence_tier"] = "gold"
        return payload

    if dry_run or not (settings.provider_api_key_configured and gold_set):
        report = run_benchmark(reference_extractor, GOLD_SET, store=store, kind="dry_run")
    else:
        from compass_agent.llm import LLMClient

        llm = LLMClient(
            api_key=settings.provider_api_key,
            provider=settings.llm_provider,
            concurrency=settings.llm_concurrency,
        )
        report = run_benchmark(
            lambda text, title: llm.enrich(text, title=title).payload,
            GOLD_SET,
            store=store,
            kind="llm",
        )
    print_benchmark_report(report)
    return 0


def cmd_metrics(settings: Settings, problems: list[str]) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.metrics import compute_metrics, print_metrics

    report = compute_metrics(store_db=settings.store_db, collector_db=settings.candidate_db)
    print_metrics(report)
    return 0


def cmd_campaign(settings: Settings, problems: list[str], action: str, sources: int) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.db import ensure_collector_db
    from compass_agent.evidence_ops import load_records, run_evidence_ops
    from compass_agent.gap_analysis import analyze_gaps
    from compass_agent.store import AgentStore

    collector_db = ensure_collector_db(path=settings.candidate_db, allow_download=settings.auto_download_db)
    if collector_db:
        try:
            from compass_agent.evidence_ops import backfill_collector_db
            backfill_collector_db(collector_db)
        except Exception:
            pass
    if not collector_db:
        print("No collector DB available (AGENT_CANDIDATE_DB).")
        return 1
    store = AgentStore(db_path=settings.store_db or "")

    if action == "plan":
        gaps = analyze_gaps(load_records(collector_db))
        print("Evidence gaps (ranked by expected impact):")
        for g in gaps[:8]:
            print(
                f"  {g.expected_impact:.2f}  {g.workflow:<28s} {g.business_function:<18s} "
                f"records={g.total_records} gold={g.gold} missing={','.join(g.missing_fields) or '-'}"
            )
        return 0

    if action == "list":
        campaigns = store.list_campaigns()
        if not campaigns:
            print("No campaigns.")
            return 0
        for c in campaigns:
            print(
                f"  {c['id'][:8]} {c['status']:<9s} {c['workflow'][:40]:<42s} "
                f"discovered={c['discovered']} accepted={c['accepted']} rejected={c['rejected']} "
                f"cost=${c['cost_usd']:.4f}"
            )
        return 0

    if action == "archive":
        archived = 0
        for c in store.list_campaigns():
            if c["status"] != "archived":
                store.update_campaign(c["id"], status="archived")
                archived += 1
        print(f"Archived {archived} campaign(s).")
        return 0

    if action == "run":
        discovery = _build_discovery(settings, store, collector_db)
        if discovery is None:
            print("Discovery unavailable (need API key + AGENT_SYNC_TOKEN).")
            return 1
        result = run_evidence_ops(store, collector_db, discovery, max_sources=sources)
        print(f"Evidence ops pass: campaign={result.get('campaign')} "
              f"discovered={result.get('discovered')} accepted={result.get('accepted')} "
              f"rejected={result.get('rejected')} cost=${result.get('cost_usd', 0):.4f}")
        reasons = result.get("rejections") or []
        if reasons:
            from collections import Counter

            counts = Counter(reasons)
            print("  rejections:", dict(counts))
        return 0
    return 0


def cmd_libraries(settings: Settings, problems: list[str], action: str, library_id: str, pages: int) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.db import ensure_collector_db
    from compass_agent.evidence_ops import run_evidence_ops
    from compass_agent.libraries import (
        ensure_libraries,
        library_score,
        prioritize_libraries,
        run_library,
    )
    from compass_agent.store import AgentStore

    collector_db = ensure_collector_db(path=settings.candidate_db, allow_download=settings.auto_download_db)
    if collector_db:
        try:
            from compass_agent.evidence_ops import backfill_collector_db
            backfill_collector_db(collector_db)
        except Exception:
            pass
    if not collector_db:
        print("No collector DB available (AGENT_CANDIDATE_DB).")
        return 1
    store = AgentStore(db_path=settings.store_db or "")
    ensure_libraries(store)

    if action == "status":
        libs = store.list_libraries()
        if not libs:
            print("No libraries registered.")
            return 0
        total_processed = sum(l["processed"] for l in libs)
        total_accepted = sum(l["accepted"] for l in libs)
        total_cost = sum(l["cost_usd"] for l in libs)
        print(f"Implementation Intelligence Library — Source Library health")
        print(f"  libraries: {len(libs)} | pages processed: {total_processed} | "
              f"accepted: {total_accepted} | cost: ${total_cost:.4f}")
        print(f"  {'library':<28s} {'cat':<12s} {'acq':<10s} {'proc':>5s} {'acc':>4s} "
              f"{'rej':>4s} {'acc%':>5s} {'cost':>7s}")
        for l in sorted(libs, key=lambda x: -library_score(x)):
            acq = (l.get("acquisition") or {}).get("preferred", "static")
            print(f"  {l['name'][:28]:<28s} {l['category'][:12]:<12s} {acq[:10]:<10s} "
                  f"{l['processed']:>5d} {l['accepted']:>4d} {l['rejected']:>4d} "
                  f"{l['acceptance_rate']*100:>4.0f}% ${l['cost_usd']:.4f}")
        return 0

    if action == "rank":
        print("Highest-value libraries right now:")
        for i, l in enumerate(prioritize_libraries(store), 1):
            print(f"  {i}. {l['name']} (score {library_score(l)}) — "
                  f"processed={l['processed']} accepted={l['accepted']}")
        return 0

    if action == "crawl":
        discovery = _build_discovery(settings, store, collector_db)
        if discovery is None:
            print("Discovery unavailable (need API key + AGENT_SYNC_TOKEN).")
            return 1
        libs = store.list_libraries()
        target = [l for l in libs if l["id"] == library_id or l["name"].lower() == library_id.lower()]
        if not target:
            print(f"Library not found: {library_id}. Available: {', '.join(l['id'] for l in libs)}")
            return 1
        result = run_library(store, target[0], discovery, None, max_pages=pages)
        print(f"Library crawl {result['library']}: pages={result['pages_processed']} "
              f"accepted={result['accepted']} rejected={result['rejected']} cost=${result['cost_usd']:.4f}")
        return 0
    return 0


def cmd_roi_search(settings: Settings, problems: list[str], queries: int, limit: int, dry_run: bool) -> int:
    """Run a mass Google search campaign for ROI case studies using OpenCLI."""
    if problems:
        return _print_config_errors(problems)
    if not settings.provider_api_key_configured:
        key_env = settings.missing_provider_key_env or "provider API key"
        print(f"WARNING: {key_env} not set — ingestion will skip LLM extraction.")
    from compass_agent.discovery import (
        DiscoveryPipeline,
        DuckDuckGoSearch,
        GoogleSearch,
        HttpFetcher,
        IngestPublisher,
        SourcePlanner,
    )
    from compass_agent.llm import LLMClient
    from compass_agent.store import AgentStore

    store = AgentStore(db_path=settings.store_db or "")
    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=min(settings.llm_concurrency, 4),
    )
    ingest = IngestPublisher(
        api_url=settings.compass_api_url,
        token=settings.sync_token,
        enabled=bool(settings.sync_token),
    )
    pipeline = DiscoveryPipeline(
        planner=SourcePlanner(
            backends=[GoogleSearch(), DuckDuckGoSearch()],
            max_per_query=limit,
        ),
        fetcher=HttpFetcher(),
        llm=llm,
        ingest=ingest,
    )

    if dry_run:
        from compass_agent.discovery import ROI_QUERIES
        print(f"Would run {min(queries, len(ROI_QUERIES))} Google searches ({limit} results each):")
        for q in ROI_QUERIES[:queries]:
            print(f"  google search \"{q}\" --limit {limit}")
        return 0

    from compass_agent.discovery import ROI_QUERIES
    actual_queries = min(queries, len(ROI_QUERIES))
    print(f"Starting ROI search campaign: {actual_queries} queries × {limit} results = ~{actual_queries * limit} candidates")
    print(f"Using: Google search via OpenCLI + DuckDuckGo fallback")
    print(f"Ingesting to: {settings.compass_api_url}/api/evidence/ingest\n")

    total_discovered = 0
    total_accepted = 0
    total_rejected = 0
    total_cost = 0.0

    for i, q in enumerate(ROI_QUERIES[:actual_queries], 1):
        gc = GoogleSearch()
        results = gc.search(q, max_results=limit)
        urls = [r["url"] for r in results if r.get("url")]
        print(f"  [{i}/{actual_queries}] google search \"{q[:60]}...\" → {len(urls)} results")

        for url in urls:
            try:
                text = pipeline.fetcher.fetch(url)
            except Exception:
                text = ""
            if len(text.strip()) < 120:
                total_rejected += 1
                continue
            try:
                from compass_agent.discovery import DiscoveryReport
                report = DiscoveryReport(workflow="ROI case study", business_function="cross-functional")
                pipeline._extract_and_ingest(text, {"url": url, "title": ""}, None, report)
                total_accepted += report.accepted
                total_rejected += report.rejected
                total_cost += report.cost_usd
            except Exception as exc:
                total_rejected += 1
            total_discovered += 1

        if i % 10 == 0:
            print(f"  Progress: {total_discovered} discovered, {total_accepted} accepted, "
                  f"{total_rejected} rejected, cost=${total_cost:.4f}")

    print(f"\nROI Search Complete:")
    print(f"  Queries run: {actual_queries}")
    print(f"  Discovered: {total_discovered}")
    print(f"  Accepted: {total_accepted}")
    print(f"  Rejected: {total_rejected}")
    print(f"  Total cost: ${total_cost:.4f}")
    return 0


def cmd_eval(settings: Settings, problems: list[str], action: str) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.db import ensure_collector_db
    from compass_agent.evidence_ops import load_records
    from compass_agent.retrieval_eval import (
        field_sensitivity,
        print_eval_report,
        run_retrieval_eval,
        weight_sensitivity,
    )

    collector_db = ensure_collector_db(path=settings.candidate_db, allow_download=settings.auto_download_db)
    if collector_db:
        try:
            from compass_agent.evidence_ops import backfill_collector_db
            backfill_collector_db(collector_db)
        except Exception:
            pass
    if not collector_db:
        print("No collector DB available (AGENT_CANDIDATE_DB).")
        return 1
    records = load_records(collector_db)
    if not records:
        print("No records to evaluate.")
        return 1
    print(f"Evaluating against {len(records)} records.")
    if action == "retrieval":
        print_eval_report(run_retrieval_eval(records))
    elif action == "sensitivity":
        print("Field sensitivity (top-25 rank displacement / top-1 flip rate):")
        for field, res in field_sensitivity(records).items():
            print(f"  {field}: rank_delta={res['rank_delta']} top1_flip={res['top1_flip_rate']}")
        print("\nWeight sensitivity (top-25 rank displacement per ±0.05 perturb):")
        for w, delta in weight_sensitivity(records).items():
            print(f"  {w}: {delta}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    settings, problems = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "status":
        return cmd_status(settings, problems)
    if args.command == "daemon":
        return cmd_daemon(settings, problems)
    if args.command == "benchmark":
        return cmd_benchmark(settings, problems, dry_run=args.dry_run, gold_set=args.gold_set)
    if args.command == "metrics":
        return cmd_metrics(settings, problems)
    if args.command == "campaign":
        return cmd_campaign(settings, problems, args.action, args.sources)
    if args.command == "libraries":
        return cmd_libraries(settings, problems, args.action, args.library, args.pages)
    if args.command == "roi-search":
        return cmd_roi_search(settings, problems, args.queries, args.limit, args.dry_run)
    if args.command == "eval":
        return cmd_eval(settings, problems, args.action)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
