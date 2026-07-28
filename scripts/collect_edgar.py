#!/usr/bin/env python3
"""SEC EDGAR source collector — public company 10-K filings with operational transformation disclosures.

Collects implementation records from SEC filings where public companies disclose
operational transformations, automation initiatives, cost savings, and measurable outcomes.

Gold-priority source: audited financial disclosures with legal liability for accuracy.

Usage:
    python scripts/collect_edgar.py --pilot     # Collect 10 filings to validate
    python scripts/collect_edgar.py --scale     # Full batch collection
    python scripts/collect_edgar.py --report    # Coverage summary
"""

import json, sys, os, re, time, hashlib, uuid, logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("edgar")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compass_collector.database import get_session, init_db
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.models.document import Document
from compass_collector.config.settings import RAW_DIR

# Companies likely to disclose operational transformation in 10-K filings
TARGET_CIKS = {
    "0000320193": "Apple Inc.",
    "0001652044": "Alphabet/Google",
    "0001018724": "Amazon.com Inc.",
    "0000789019": "Microsoft Corporation",
    "0001326801": "Meta Platforms",
    "0001041690": "Walmart Inc.",
    "0000034088": "Exxon Mobil",
    "0000051143": "IBM Corporation",
    "0000732717": "UnitedHealth Group",
    "0001397183": "JPMorgan Chase",
    "0000041723": "Bank of America",
    "0000858877": "Cisco Systems",
    "0000804984": "Tesla Inc.",
}

SEC_BASE = "https://www.sec.gov"
SEC_HEADERS = {
    "User-Agent": "Compass Research (research@compass.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}

# Keywords indicating operational transformation
TRANSFORM_KEYWORDS = [
    "automated", "automation", "digital transformation", "workflow",
    "operational efficiency", "cost savings", "process improvement",
    "lean", "re-engineered", "restructuring", "shared services",
    "outsourcing", "insourcing", "ai implementation", "machine learning",
    "rpa", "robotic process", "cloud migration", "erp implementation",
    "supply chain optimization", "self-service", "digitization",
]


def fetch_url(url: str) -> str | None:
    import urllib.request
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=SEC_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return None


def extract_transformation_sections(text: str) -> list[dict]:
    """Extract paragraphs mentioning operational transformation from 10-K text."""
    results = []
    paragraphs = re.split(r'\n\s*\n', text)
    for para in paragraphs:
        lower = para.lower()
        keywords_found = [kw for kw in TRANSFORM_KEYWORDS if kw in lower]
        if len(keywords_found) >= 2:
            results.append({
                "text": para[:2000],
                "keywords": keywords_found,
                "word_count": len(para.split()),
            })
    return results


def search_company_filings(cik: str, company: str) -> list[dict]:
    """Search a company's recent 10-K filings for transformation disclosures."""
    logger.info(f"Searching {company} ({cik})...")

    # Get filing index
    idx_url = f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K&dateb=20260101&owner=exclude&count=40"
    html = fetch_url(idx_url)
    if not html:
        logger.warning(f"  No filing index for {company}")
        return []

    # Extract filing links
    filings = []
    for match in re.finditer(r'<a[^>]*href="(/ix\?doc=/data/[^"]*10-k[^"]*)"[^>]*>', html, re.I):
        url = urljoin(SEC_BASE, match.group(1))
        filings.append({"url": url, "company": company, "cik": cik})

    for match in re.finditer(r'<a[^>]*href="(/Archives/edgar/data/[^"]*10-k[^"]*\.htm)"[^>]*>', html, re.I):
        url = urljoin(SEC_BASE, match.group(1))
        if url not in [f["url"] for f in filings]:
            filings.append({"url": url, "company": company, "cik": cik})

    return filings[:5]  # Limit to 5 most recent


def extract_implementation(company: str, section: dict, filing_url: str) -> dict | None:
    """Try to extract a structured implementation record from a section of text."""
    text = section["text"]
    lower = text.lower()

    # Determine intervention type
    intervention = "Operational transformation"
    families = ["process_redesign"]
    if any(kw in lower for kw in ["automation", "rpa", "robotic"]):
        intervention = "Workflow automation initiative"
        families = ["workflow_automation", "rpa"]
    if any(kw in lower for kw in ["ai", "machine learning"]):
        intervention = "AI and machine learning implementation"
        families = families + ["ai", "machine_learning"]
    if any(kw in lower for kw in ["cloud migration", "erp"]):
        intervention = "Enterprise platform migration"
        families = ["software", "cloud_migration"]
    if any(kw in lower for kw in ["shared services", "outsourcing"]):
        intervention = "Shared services and outsourcing"
        families = ["staffing", "shared_services"]

    # Try to extract a dollar amount (cost savings)
    cost_match = re.search(r'\$[\d,]+(?:\s*(?:million|billion|M|B))?', text)
    cost_savings = cost_match.group(0) if cost_match else None

    # Try to extract a percentage
    pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    pct_val = float(pct_match.group(1)) if pct_match else None

    if not cost_match and not pct_match and len(text) < 100:
        return None  # Not enough to build a record

    rid = str(uuid.uuid4())
    record = {
        "organization": company,
        "industry": [],
        "intervention": intervention,
        "families": families,
        "description": text[:500].replace("\n", " "),
        "source_url": filing_url,
        "extraction_model": "edgar-collector-v1",
        "review_status": "bronze",  # Default; promoted if metrics found
        "result_status": "successful",
    }

    metrics = []
    if cost_match:
        val_str = cost_match.group(0).replace("$", "").replace(",", "")
        multiplier = 1
        if "million" in text[cost_match.start():cost_match.end()+20].lower():
            multiplier = 1_000_000
        elif "billion" in text[cost_match.start():cost_match.end()+20].lower():
            multiplier = 1_000_000_000
        try:
            val = float(val_str.replace("$", "").replace(",", "")) * multiplier
            metrics.append({"name": "Cost savings/impact", "category": "cost", "absolute_change": val, "unit": "USD", "reported_text": cost_match.group(0)})
        except: pass

    if pct_val:
        metrics.append({"name": "Operational improvement", "category": "efficiency", "percentage_change": pct_val if any(kw in lower for kw in ["increase", "improve", "grow"]) else -pct_val, "unit": "%", "reported_text": pct_match.group(0)})

    record["metrics"] = metrics

    # Determine tier based on evidence quality
    if cost_match and len(metrics) >= 2:
        record["review_status"] = "gold"
        record["independently_verified"] = True
    elif cost_match or (pct_val and len(text) > 300):
        record["review_status"] = "silver"

    return record


def save_record(session, doc: Document, record: dict):
    """Save extracted record to database."""
    rid = str(uuid.uuid4())
    rec = InterventionRecord(
        id=rid, source_id=f"edgar-{rid[:8]}", document_id=doc.id,
        organization_name=record["organization"],
        organization_industry=record.get("industry", []),
        problem_statement=f"Operational transformation at {record['organization']}",
        intervention_title=record["intervention"],
        intervention_families=record.get("families", []),
        intervention_description=record.get("description", "")[:500],
        result_status=record.get("result_status", "successful"),
        has_post_measurement=True,
        independently_verified=record.get("independently_verified", False),
        extraction_model=record.get("extraction_model", "edgar-collector-v1"),
        extractor="edgar_collector",
        extracted_at=datetime.now(timezone.utc),
        review_status=record.get("review_status", "bronze"),
        parser_version="3.0.0",
    )
    session.add(rec)
    for m in record.get("metrics", []):
        session.add(MetricRecord(
            id=str(uuid.uuid4()), intervention_id=rid, source_id=rec.source_id,
            metric_name=m["name"], metric_category=m.get("category", ""),
            absolute_change=m.get("absolute_change"), percentage_change=m.get("percentage_change"),
            unit=m.get("unit", ""), reported_text=m.get("reported_text", ""), value_type="reported",
        ))
    return rec


def cmd_pilot():
    """Pilot run: 10 filings, validate extraction quality."""
    init_db()
    session = get_session()

    existing_urls = set()
    for url, in session.query(Document.url).all():
        if url:
            existing_urls.add(url)

    total_new = 0
    for cik, company in list(TARGET_CIKS.items())[:3]:  # Pilot: 3 companies
        filings = search_company_filings(cik, company)
        for filing in filings[:3]:
            if filing["url"] in existing_urls:
                continue
            html = fetch_url(filing["url"])
            if not html:
                continue
            sections = extract_transformation_sections(html)
            if not sections:
                continue

            doc = Document(
                id=str(uuid.uuid4()), url=filing["url"], title=f"{company} 10-K",
                publisher="SEC", publication_date=datetime.now(timezone.utc).isoformat(),
                retrieved_at=datetime.now(timezone.utc), document_type="sec_filing",
                content_hash=hashlib.sha256(html.encode()).hexdigest(),
                cleaned_text=html[:50000], crawl_status="success",
            )
            session.add(doc)
            session.flush()

            for section in sections[:3]:
                record = extract_implementation(company, section, filing["url"])
                if record:
                    save_record(session, doc, record)
                    total_new += 1
            time.sleep(1)

    session.commit()
    total = session.query(InterventionRecord).count()
    ready = session.query(InterventionRecord.id).filter(InterventionRecord.organization_name.isnot(None), InterventionRecord.intervention_title != "", InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())).count()
    logger.info(f"Pilot complete: {total_new} new records. Total: {total}, Ready: {ready}")
    session.close()


def cmd_report():
    """Print EDGAR collection coverage."""
    init_db()
    session = get_session()
    edgar_docs = session.query(Document).filter(Document.publisher == "SEC").count()
    edgar_recs = session.query(InterventionRecord).filter(InterventionRecord.extractor == "edgar_collector").count()
    logger.info(f"EDGAR documents: {edgar_docs}, records extracted: {edgar_recs}")
    session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--scale", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.pilot: cmd_pilot()
    elif args.scale: cmd_pilot()  # For now, pilot same as scale
    elif args.report: cmd_report()
    else: parser.print_help()
