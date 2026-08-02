"""Command-line interface for the Compass Evidence Agent.

Commands::

    python -m compass_agent --help
    python -m compass_agent status
    python -m compass_agent daemon
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from compass_agent import __version__
from compass_agent.config import Settings, load_settings
from compass_agent.daemon import Daemon, check_engine_health, print_startup_summary


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
    return parser


def _print_config_errors(problems: list[str]) -> int:
    print("Compass Evidence Agent", flush=True)
    print("Status: configuration error", flush=True)
    for problem in problems:
        print(f"  - {problem}", flush=True)
    return 1


def _build_enrichment_workflow(settings: Settings, budget):
    """Build the budget-controlled enrichment pipeline, or None when no key."""
    from compass_agent.claim import ClaimQueue, CollectorCandidateProvider
    from compass_agent.daemon import BudgetTracker
    from compass_agent.enrich import EnrichmentPipeline
    from compass_agent.llm import LLMClient
    from compass_agent.publish import NoopPublisher, Publisher
    from compass_agent.store import AgentStore
    from compass_agent.workflow import EnrichmentWorkflow

    if not settings.provider_api_key_configured:
        return None

    db_path = os.environ.get("AGENT_CANDIDATE_DB", os.environ.get("COLLECTOR_DATABASE_URL", ""))
    if db_path.startswith("sqlite:///"):
        db_path = db_path[len("sqlite:///"):]

    store = AgentStore(db_path=settings.state_file or "")
    provider = CollectorCandidateProvider(db_path=db_path) if db_path else None
    if provider is None:
        return None

    queue = ClaimQueue(provider=provider, store=store)
    llm = LLMClient(
        api_key=settings.provider_api_key,
        provider=settings.llm_provider,
        concurrency=settings.llm_concurrency,
    )
    publisher = (
        Publisher(db_path=db_path, enabled=settings.auto_publish)
        if db_path
        else NoopPublisher()
    )
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
    enrichment = _build_enrichment_workflow(settings, budget)
    if enrichment is None:
        print("NOTE: enrichment pipeline inactive (no API key or no candidate DB).", flush=True)
    daemon = Daemon(settings, budget=budget, enrichment=enrichment)
    return daemon.run()


def cmd_benchmark(settings: Settings, problems: list[str], dry_run: bool, gold_set: bool) -> int:
    if problems:
        return _print_config_errors(problems)
    from compass_agent.benchmark import GOLD_SET, print_benchmark_report, run_benchmark
    from compass_agent.store import AgentStore

    store = AgentStore(db_path=settings.state_file or "")

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

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
