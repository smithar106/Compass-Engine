import sys
import json
from pathlib import Path

from compass_collector.database import init_db, get_session
from compass_collector.pipeline.orchestrator import PipelineOrchestrator
from compass_collector.engine.source_discovery import SourceDiscoveryEngine
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag


def cmd_init():
    init_db()
    print("Database initialized.")


def cmd_sources_import(path: str):
    engine = SourceDiscoveryEngine()
    sources = engine.import_yaml(path)
    print(f"Imported {len(sources)} sources.")


def cmd_sources_list():
    engine = SourceDiscoveryEngine()
    sources = engine.list_sources()
    for s in sources:
        status = "✓" if s.enabled else "✗"
        print(f"  {status} {s.source_domain:40s} ({s.publisher:20s}) tier={s.reliability_tier} rate={s.rate_limit}/s")


def cmd_discover(problem: str = None):
    pipe = PipelineOrchestrator()
    sources = pipe.discover()
    print(f"Registry has {len(sources)} source(s).")
    if problem:
        print(f"Ready to search for: {problem}")


def cmd_crawl(source_id: str = None, limit: int = None):
    pipe = PipelineOrchestrator()
    docs = pipe.crawl_all(source_id, limit)
    print(f"Crawled {len(docs)} documents.")


def cmd_parse():
    pipe = PipelineOrchestrator()
    count = pipe.process_pending()
    print(f"Processed {count} pending documents.")


def cmd_extract():
    pipe = PipelineOrchestrator()
    count = pipe.process_pending()
    print(f"Extracted interventions from {count} documents.")


def cmd_validate():
    session = get_session()
    try:
        flags = session.query(QualityFlag).all()
        by_type = {}
        for f in flags:
            by_type[f.flag_name] = by_type.get(f.flag_name, 0) + 1
        print("Quality flags:")
        for name, count in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"  {name}: {count}")
        print(f"Total: {len(flags)} flags on {session.query(QualityFlag).count()} records")
    finally:
        session.close()


def cmd_deduplicate():
    pipe = PipelineOrchestrator()
    result = pipe.deduplicate()
    print(f"Duplicates found: {result['exact']} exact, {result['near']} near, {result['same_study']} same case study")


def cmd_export(format: str = "jsonl"):
    pipe = PipelineOrchestrator()
    pipe.export([format])
    print(f"Exported to {format.upper()}.")


def cmd_status():
    pipe = PipelineOrchestrator()
    status = pipe.status()
    print("=== Collector Status ===")
    for k, v in status.items():
        print(f"  {k}: {v}")


def cmd_retry():
    session = get_session()
    try:
        failed = session.query(Document).filter_by(crawl_status="failed").all()
        for doc in failed:
            doc.crawl_status = "pending"
        session.commit()
        print(f"Reset {len(failed)} failed documents to pending.")
    finally:
        session.close()


def cmd_reset():
    import os
    from compass_collector.config.settings import DATA_DIR
    db_path = DATA_DIR / "collector.db"
    if db_path.exists():
        os.remove(db_path)
        print("Database removed. Run 'init' to recreate.")
    else:
        print("No database found.")
