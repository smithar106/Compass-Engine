#!/usr/bin/env python3
"""Real Evidence Collection Pipeline

Collects real implementation case studies from the web using the existing
CrawlEngine and LLM extraction pipeline. This is the production data collection
tool for building the Compass evidence graph.

Usage:
    # Set your API key first
    export ANTHROPIC_API_KEY=sk-ant-...

    # Run full pipeline
    python scripts/collect_evidence.py --all

    # Step by step
    python scripts/collect_evidence.py --discover      # Find new case study URLs
    python scripts/collect_evidence.py --crawl          # Fetch documents
    python scripts/collect_evidence.py --extract        # LLM extraction
    python scripts/collect_evidence.py --validate       # Validate & insert

    # Coverage report
    python scripts/collect_evidence.py --report

Sources:
    - company case study pages
    - industry transformation reports
    - published ROI analyses
"""

import argparse
import json
import sys
import logging
import time
import csv
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("collect")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session, init_db
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.models.document import Document
from compass_collector.engine.crawl import CrawlEngine
from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator
from compass_collector.config.settings import RAW_DIR
from sqlalchemy import func

# ---------------------------------------------------------------------------
# SOURCE CONFIGURATION — Case study sites to discover and crawl
# ---------------------------------------------------------------------------

CASE_STUDY_SOURCES = [
    # Major automation/platform vendors — high-quality case studies
    {"name": "UiPath Case Studies", "type": "sitemap", "url": "https://www.uipath.com/resources/case-studies/sitemap.xml"},
    {"name": "Automation Anywhere", "type": "sitemap", "url": "https://www.automationanywhere.com/sitemap.xml"},
    {"name": "Salesforce Case Studies", "type": "sitemap", "url": "https://www.salesforce.com/sitemap.xml"},
    {"name": "ServiceNow Case Studies", "type": "sitemap", "url": "https://www.servicenow.com/sitemap.xml"},
    {"name": "Microsoft Customer Stories", "type": "sitemap", "url": "https://customers.microsoft.com/sitemap.xml"},
    {"name": "AWS Case Studies", "type": "sitemap", "url": "https://aws.amazon.com/sitemap.xml"},
    {"name": "Google Cloud Case Studies", "type": "sitemap", "url": "https://cloud.google.com/sitemap.xml"},
    {"name": "Workday Customer Stories", "type": "sitemap", "url": "https://www.workday.com/sitemap.xml"},
]

# Direct case study URLs (high-value, known operational transformations)
CURATED_STUDIES = [
    "https://www.uipath.com/resources/automation-case-studies/teleperformance",
    "https://www.uipath.com/resources/automation-case-studies/equifax",
    "https://www.uipath.com/resources/automation-case-studies/cognizant",
    "https://www.uipath.com/resources/automation-case-studies/dhl",
    "https://www.uipath.com/resources/automation-case-studies/nhs",
    "https://www.uipath.com/resources/automation-case-studies/bank-of-america",
    "https://customers.microsoft.com/en-us/story/",
    "https://aws.amazon.com/solutions/case-studies/",
    "https://cloud.google.com/customers/",
    "https://www.servicenow.com/customers/",
]

# Search terms for finding operational transformation case studies
SEARCH_QUERIES = [
    "RPA implementation case study results",
    "workflow automation case study operational improvement",
    "AI transformation case study business outcomes",
    "process automation ROI case study",
    "digital transformation measurable outcomes",
    "lean process improvement case study results",
    "operational efficiency automation case study",
]


def cmd_discover(args):
    """Discover new case study URLs from sitemaps and search."""
    engine = CrawlEngine()
    discovered = []
    
    for source in CASE_STUDY_SOURCES[:3]:  # Rate limit: process 3 at a time
        logger.info(f"Fetching sitemap: {source['name']}")
        try:
            urls = engine.fetch_sitemap(source["url"])
            # Filter for case-study-like URLs
            for u in urls:
                if any(kw in u.lower() for kw in ["case-study", "customer-story", "customer", "success-story"]):
                    discovered.append({"url": u, "source": source["name"], "type": "sitemap"})
            logger.info(f"  Found {len(urls)} URLs, {sum(1 for u in urls if 'case' in u.lower())} case-study related")
        except Exception as e:
            logger.warning(f"  Failed: {e}")
        time.sleep(2)
    
    # Save discovered URLs
    out = RAW_DIR / "discovered_sources.jsonl"
    with open(out, "w") as f:
        for d in discovered:
            f.write(json.dumps(d) + "\n")
    logger.info(f"Discovered {len(discovered)} potential case study URLs → {out}")


def cmd_crawl(args):
    """Crawl discovered and curated URLs to fetch documents."""
    engine = CrawlEngine()
    init_db()
    session = get_session()
    
    # Load URLs to crawl
    urls_to_crawl = list(CURATED_STUDIES)
    discovered_file = RAW_DIR / "discovered_sources.jsonl"
    if discovered_file.exists():
        with open(discovered_file) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    urls_to_crawl.append(data["url"])
                except: pass
    
    # Remove duplicates and already-crawled
    existing_urls = set()
    for url, in session.query(Document.url).all():
        existing_urls.add(url)
    
    urls_to_crawl = [u for u in urls_to_crawl if u not in existing_urls]
    logger.info(f"Crawling {len(urls_to_crawl)} new URLs...")
    
    for i, url in enumerate(urls_to_crawl[:100]):  # Max 100 per run
        try:
            doc = engine.fetch(url, source_id=f"collect-v1")
            if doc and doc.cleaned_text and len(doc.cleaned_text) > 500:
                session.add(doc)
                session.commit()
                logger.info(f"  [{i+1}/{len(urls_to_crawl)}] Fetched: {url[:80]}")
            else:
                logger.warning(f"  [{i+1}/{len(urls_to_crawl)}] Too short or failed: {url[:60]}")
        except Exception as e:
            logger.warning(f"  [{i+1}/{len(urls_to_crawl)}] Error: {e}")
        time.sleep(1)
    
    total_docs = session.query(Document).count()
    logger.info(f"\nTotal documents in database: {total_docs}")
    session.close()


def cmd_extract(args):
    """Run LLM extraction on unprocessed documents."""
    api_key = args.api_key or __import__('os').environ.get("ANTHROPIC_API_KEY") or __import__('os').environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
        sys.exit(1)
    
    orch = ExtractionOrchestrator()
    orch.set_api_key(api_key)
    
    # Load unprocessed documents
    init_db()
    session = get_session()
    processed_ids = set()
    for rid, in session.query(InterventionRecord.document_id).filter(InterventionRecord.document_id.isnot(None)).all():
        processed_ids.add(rid)
    
    unprocessed = session.query(Document).filter(
        Document.cleaned_text.isnot(None),
        Document.crawl_status == "success"
    ).limit(50).all()
    if processed_ids:
        unprocessed = [d for d in unprocessed if d.id not in processed_ids]
    
    logger.info(f"Found {len(unprocessed)} unprocessed documents")
    session.close()
    
    if not unprocessed:
        logger.info("No documents to process.")
        return
    
    documents = [{"id": d.id, "title": d.title or "", "url": d.url or "", "text": d.cleaned_text or "", "source_type": "web"} for d in unprocessed]
    
    # Run extraction pipeline
    results, relevance_counts = orch.run_relevance_filter(documents)
    logger.info(f"Relevance: {relevance_counts}")
    
    relevant = [d for d in results if d["classification"] in ("high_relevance", "possible_relevance")]
    if relevant:
        extraction_results = orch.run_extraction(relevant)
        validated = orch.validator.validate_all(extraction_results)
        orch.save_to_database(validated)
        logger.info(f"Extracted and saved {len(validated)} new implementations")
    else:
        logger.info("No relevant documents found in this batch.")


def cmd_report(args):
    """Print coverage report of the current evidence graph."""
    init_db()
    session = get_session()
    
    total = session.query(InterventionRecord).count()
    with_metrics = session.query(MetricRecord.intervention_id).distinct().count()
    ready = session.query(InterventionRecord.id).filter(
        InterventionRecord.organization_name.isnot(None),
        InterventionRecord.intervention_title != "",
        InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())
    ).count()
    models = dict(session.query(InterventionRecord.extraction_model, func.count(InterventionRecord.id)).group_by(InterventionRecord.extraction_model).all())
    reviews = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())
    docs = session.query(Document).count()
    processed_docs = set(r[0] for r in session.query(InterventionRecord.document_id).filter(InterventionRecord.document_id.isnot(None)).all() if r[0])
    total_docs_with_text = session.query(Document).filter(Document.cleaned_text.isnot(None)).count()
    unprocessed = total_docs_with_text - len(processed_docs)
    
    print("\n" + "=" * 60)
    print("EVIDENCE GRAPH — REAL DATA REPORT")
    print("=" * 60)
    print(f"  Documents in database:        {docs}")
    print(f"  Extracted implementations:    {total}")
    print(f"  With metrics:                 {with_metrics}")
    print(f"  Recommendation-ready:         {ready}")
    print(f"  Unprocessed documents:        {max(0, unprocessed)}")
    print(f"\n  By extraction model:")
    for m, c in sorted(models.items(), key=lambda x: -x[1]):
        print(f"    {m}: {c}")
    print(f"\n  By tier:")
    for t in ["gold", "silver", "bronze"]:
        print(f"    {t}: {reviews.get(t, 0)}")
    print(f"\n  Gap to 1,000: {max(0, 1000 - total)}")
    print("=" * 60)
    
    session.close()


def cmd_reset(args):
    """Remove synthetic data, keep only real extractions."""
    init_db()
    session = get_session()
    
    synths = session.query(InterventionRecord).filter(
        InterventionRecord.extraction_model.in_(["bulk-v1", "seed-v1"])
    ).all()
    
    logger.info(f"Removing {len(synths)} synthetic records...")
    for rec in synths:
        session.query(MetricRecord).filter_by(intervention_id=rec.id).delete()
        session.delete(rec)
    session.commit()
    
    total = session.query(InterventionRecord).count()
    logger.info(f"Real records remaining: {total}")
    session.close()


def cmd_export(args):
    """Export evidence graph to CSV."""
    init_db()
    session = get_session()
    desktop = Path.home() / "Desktop" / "compass_real_evidence.csv"
    
    records = session.query(InterventionRecord).order_by(InterventionRecord.review_status, InterventionRecord.organization_name).all()
    with open(desktop, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Organization", "Industry", "Intervention", "Tier", "Status", "Problem", "Metrics", "Has Timeline", "Source Model"])
        for r in records:
            mc = session.query(MetricRecord).filter_by(intervention_id=r.id).count()
            ind = ", ".join(r.organization_industry) if r.organization_industry else ""
            w.writerow([r.organization_name, ind, r.intervention_title, r.review_status, r.result_status, r.problem_statement[:80] if r.problem_statement else "", mc, "yes" if r.intervention_implementation_time_value else "no", r.extraction_model])
    
    logger.info(f"Exported {len(records)} real implementations → {desktop}")
    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compass Real Evidence Collection Pipeline")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    parser.add_argument("--discover", action="store_true", help="Discover new case study URLs")
    parser.add_argument("--crawl", action="store_true", help="Crawl discovered URLs")
    parser.add_argument("--extract", action="store_true", help="Run LLM extraction")
    parser.add_argument("--validate", action="store_true", help="Validate and save")
    parser.add_argument("--report", action="store_true", help="Coverage report")
    parser.add_argument("--reset", action="store_true", help="Remove synthetic data")
    parser.add_argument("--export", action="store_true", help="Export CSV to desktop")
    parser.add_argument("--api-key", help="LLM API key")
    parser.add_argument("--batch-size", type=int, default=50, help="Documents per batch")
    
    args = parser.parse_args()
    
    if args.reset:
        cmd_reset(args)
    elif args.report:
        cmd_report(args)
    elif args.export:
        cmd_export(args)
    elif args.discover:
        cmd_discover(args)
    elif args.crawl:
        cmd_crawl(args)
    elif args.extract:
        cmd_extract(args)
    elif args.all:
        logger.info("=== Running full collection pipeline ===")
        cmd_discover(args)
        cmd_crawl(args)
        cmd_extract(args)
        cmd_report(args)
    else:
        parser.print_help()
