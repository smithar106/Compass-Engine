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


# ---------------------------------------------------------------------------
# Ingest commands (new evidence pipeline)
# ---------------------------------------------------------------------------

def cmd_ingest_document(path_or_url: str, api_key: str = "", persist: bool = False):
    """Ingest a single document: parse → extract → (optional) graph."""
    from compass_collector.ingest.orchestrator import ingest_document
    run = ingest_document(path_or_url, api_key, persist=persist)
    return run


def cmd_ingest_crawl(url: str, max_pages: int = 50, depth: int = 2, api_key: str = ""):
    """Crawl a website, then ingest discovered documents."""
    from compass_collector.ingest.orchestrator import ingest_document
    from compass_collector.ingest.parser import fetch_url, parse_html, detect_document_type, is_url
    from compass_collector.ingest import DocumentType
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    visited = set()
    to_visit = [(url, 0)]
    results = []

    while to_visit and len(visited) < max_pages:
        current_url, current_depth = to_visit.pop(0)
        if current_url in visited or current_depth > depth:
            continue
        visited.add(current_url)

        print(f"  [{len(visited)}] {current_url[:70]}")
        try:
            html, final_url = fetch_url(current_url)
            doc = parse_html(html, url=final_url)

            # Extract claims
            if api_key:
                run = ingest_document(final_url, api_key)
                results.append(run)

            # Find more links if under max depth
            if current_depth < depth:
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = urljoin(final_url, a["href"])
                    same_domain = final_url.split("/")[2] in href if len(final_url.split("/")) > 2 else False
                    if same_domain and href not in visited and not any(skip in href for skip in ["login", "careers", "privacy", "cookie"]):
                        to_visit.append((href, current_depth + 1))
        except Exception as e:
            print(f"    Error: {e}")

    print(f"\nCrawled {len(visited)} pages, ingested {len(results)} documents.")


def cmd_ingest_status(run_id: str = ""):
    """Show latest ingestion run status."""
    from compass_collector.ingest import IngestionRun
    print(f"Ingestion run: {run_id or 'latest'}")
    print("(Run details stored in structured logs)")
