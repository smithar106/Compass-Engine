#!/usr/bin/env python3
"""Evidence collection using OpenCLI browser bridge for JS-rendered pages.

Usage:
    export DEEPSEEK_API_KEY=sk-...
    python scripts/run_collection.py --api-key "$DEEPSEEK_API_KEY"

Requires: opencli browser bridge extension installed and connected.
Test with: opencli doctor
"""

import sys, os, json, time, uuid, hashlib, subprocess, re
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session, init_db
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.engine.crawl import CrawlEngine
from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator
from sqlalchemy import func


# === SOURCE URLs ===
# These are JavaScript-rendered → need OpenCLI browser
JS_URLS = [
    # ServiceNow customer stories (confirmed working with OpenCLI)
    "https://www.servicenow.com/customers/airbus.html",
    "https://www.servicenow.com/customers/siemens.html",
    "https://www.servicenow.com/customers/uber.html",
    "https://www.servicenow.com/customers/walmart.html",
    "https://www.servicenow.com/customers/nvidia.html",
    "https://www.servicenow.com/customers/adidas.html",
    "https://www.servicenow.com/customers/honeywell.html",
    "https://www.servicenow.com/customers/fedex.html",
    "https://www.servicenow.com/customers/cvs-health.html",
    "https://www.servicenow.com/customers/lenovo.html",
    # UiPath case studies (confirmed working)
    "https://www.uipath.com/resources/automation-case-studies/equifax",
    "https://www.uipath.com/resources/automation-case-studies/dhl",
    "https://www.uipath.com/resources/automation-case-studies/nhs",
    "https://www.uipath.com/resources/automation-case-studies/cognizant",
    "https://www.uipath.com/resources/automation-case-studies/bank-of-america",
    "https://www.uipath.com/resources/automation-case-studies/teleperformance",
    "https://www.uipath.com/resources/automation-case-studies/schneider-electric",
    "https://www.uipath.com/resources/automation-case-studies/ey",
    "https://www.uipath.com/resources/automation-case-studies/credit-suisse",
    # Google Cloud customers (may need OpenCLI)
    "https://cloud.google.com/customers/spotify",
    "https://cloud.google.com/customers/hsbc",
    "https://cloud.google.com/customers/verizon",
    "https://cloud.google.com/customers/ebay",
    # Accenture case studies
    "https://www.accenture.com/us-en/case-studies/siemens-digital-transformation",
    "https://www.accenture.com/us-en/case-studies/healthcare-transformation",
    "https://www.accenture.com/us-en/case-studies/banking-automation",
    # Deloitte case studies
    "https://www.deloitte.com/us/en/case-studies/technology-transformation.html",
    "https://www.deloitte.com/us/en/case-studies/operations-automation.html",
]

# Server-rendered HTML → use requests
HTML_URLS = []


def opencli_browser_fetch(url: str, timeout: int = 60) -> str | None:
    """Fetch page content using OpenCLI browser bridge."""
    import json
    profile = os.environ.get("OPENCLI_PROFILE", "2dsmkwnt")
    try:
        # Close any existing tab first (ignore errors)
        subprocess.run(["opencli", "browser", profile, "close"], capture_output=True, text=True, timeout=10)
    except: pass

    try:
        result = subprocess.run(
            ["opencli", "browser", profile, "open", url],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return None

        time.sleep(5)

        result = subprocess.run(
            ["opencli", "browser", profile, "extract"],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                content = data.get("content", "") or data.get("text", "") or result.stdout
                if len(content) > 100:
                    return content
            except json.JSONDecodeError:
                if len(result.stdout) > 100:
                    return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def fetch_with_retry(url: str, use_browser: bool = False) -> tuple[str, str | None, str | None]:
    """Fetch URL, return (text, error, fetch_method)."""
    if use_browser:
        text = opencli_browser_fetch(url)
        if text and len(text) > 500:
            return text, None, "opencli"
        return None, "opencli_failed", "opencli"

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > 500:
                return text, None, "requests"
        return None, "too_short", "requests"
    except Exception as e:
        return None, str(e), "requests"


def fetch_url(url: str) -> tuple[str | None, str | None]:
    """Fetch URL, trying OpenCLI browser first, then requests as fallback."""
    text, err, method = fetch_with_retry(url, use_browser=True)
    if text:
        return text, method
    text2, err2, _ = fetch_with_retry(url, use_browser=False)
    return text2 if text2 else (text, err)


def save_document(session, url: str, text: str, fetch_method: str) -> Document:
    doc = Document(
        id=str(uuid.uuid4()),
        url=url,
        title=url.split("/")[-1][:100],
        retrieved_at=datetime.now(timezone.utc),
        document_type="web",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        cleaned_text=text[:100000],
        crawl_status="success",
        parser_version="3.0.0",
    )
    session.add(doc)
    session.flush()
    return doc


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", help="DeepSeek/Anthropic API key", required=True)
    parser.add_argument("--max-urls", type=int, default=30, help="Max URLs to fetch")
    parser.add_argument("--no-extract", action="store_true", help="Skip LLM extraction")
    args = parser.parse_args()

    init_db()
    session = get_session()
    existing_urls = set(u for (u,) in session.query(Document.url).all() if u)

    # === STEP 1: FETCH PAGES ===
    print("\n" + "=" * 60)
    print("STEP 1: Fetching pages (OpenCLI browser + requests)")
    print("=" * 60)

    urls = JS_URLS[:args.max_urls] + HTML_URLS[:max(0, args.max_urls - len(JS_URLS[:args.max_urls]))]
    urls = [u for u in urls if u not in existing_urls]
    print(f"  URLs to fetch: {len(urls)} (JS: {len([u for u in urls if any(d in u for d in ['microsoft','servicenow','cloud.google'])])}, HTML: {len([u for u in urls if not any(d in u for d in ['microsoft','servicenow','cloud.google'])])})")

    new_docs = 0
    for i, url in enumerate(urls):
        print(f"  [{i+1}/{len(urls)}] Fetching: {url[:70]}...")
        text, method = fetch_url(url)
        if text and len(text) > 500:
            doc = save_document(session, url, text, method or "unknown")
            new_docs += 1
            print(f"    OK ({method}, {len(text)} chars)")
        else:
            print(f"    FAILED ({method})")
        time.sleep(2)

    session.commit()
    print(f"\n  Fetched {new_docs} new documents")

    # === STEP 2: LLM EXTRACTION ===
    if not args.no_extract and args.api_key:
        print("\n" + "=" * 60)
        print("STEP 2: LLM Extraction")
        print("=" * 60)

        processed_ids = set()
        for rid, in session.query(InterventionRecord.document_id).filter(InterventionRecord.document_id.isnot(None)).all():
            if rid: processed_ids.add(rid)

        unprocessed = session.query(Document).filter(
            Document.cleaned_text.isnot(None),
            Document.crawl_status == "success",
            ~Document.id.in_(processed_ids) if processed_ids else True
        ).limit(100).all()

        print(f"  Unprocessed documents: {len(unprocessed)}")
        if unprocessed:
            orch = ExtractionOrchestrator()
            orch.set_api_key(args.api_key)
            doc_list = [{"id": d.id, "title": d.title or "", "url": d.url or "", "text": d.cleaned_text or "", "source_type": "web"} for d in unprocessed]
            results, counts = orch.run_relevance_filter(doc_list)
            print(f"  Relevance: {counts}")
            relevant = [d for d in results if d["classification"] in ("high_relevance", "possible_relevance")]
            if relevant:
                extracted = orch.run_extraction(relevant)
                validated = orch.validator.validate_all(extracted)
                orch.save_to_database(validated)
                print(f"  Extracted {len(validated)} records")

    # === STEP 3: CLASSIFY ===
    print("\n" + "=" * 60)
    print("STEP 3: Classifying tiers")
    print("=" * 60)
    pending = session.query(InterventionRecord).filter(
        InterventionRecord.review_status.in_(["pending", "tier2", "tier3", "", None])
    ).all()
    for rec in pending:
        mc = session.query(MetricRecord).filter_by(intervention_id=rec.id)
        has_q = mc.filter(MetricRecord.percentage_change.isnot(None) | MetricRecord.absolute_change.isnot(None)).count() > 0
        score = 0
        score += 20 if has_q else 10 if mc.count() > 0 else 0
        score += 15 if rec.independently_verified else 0
        score += 10 if rec.has_baseline else 0
        score += 10 if rec.intervention_implementation_time_value else 0
        score += 10 if rec.organization_employee_count else 0
        score += 10 if rec.organization_industry and rec.organization_industry not in ("[]", [""]) else 0
        score -= 10 if rec.vendor_reported and not rec.independently_verified else 0
        rec.review_status = "gold" if score >= 50 else "silver" if score >= 25 else "bronze"
    session.commit()

    # === REPORT ===
    total = session.query(InterventionRecord).count()
    ready = session.query(InterventionRecord.id).filter(
        InterventionRecord.organization_name.isnot(None),
        InterventionRecord.intervention_title != "",
        InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())
    ).count()
    docs = session.query(Document).count()
    reviews = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())

    print("\n" + "=" * 60)
    print("COLLECTION COMPLETE")
    print("=" * 60)
    print(f"  Documents:               {docs}")
    print(f"  Total implementations:   {total}")
    print(f"  Recommendation-ready:    {ready}")
    for t in ["gold", "silver", "bronze"]:
        print(f"    {t}: {reviews.get(t, 0)}")
    print(f"  Gap to 300/300/300:")
    print(f"    gold:   {max(0, 300 - reviews.get('gold', 0))}")
    print(f"    silver: {max(0, 300 - reviews.get('silver', 0))}")
    print(f"    bronze: {max(0, 300 - reviews.get('bronze', 0))}")
    print(f"\n  Total gap to 900: {max(0, 900 - total)}")
    print("=" * 60)

    # Export CSV
    import csv
    desk = Path.home() / "Desktop" / "compass_evidence.csv"
    records = session.query(InterventionRecord).order_by(InterventionRecord.review_status).all()
    with open(desk, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Organization", "Industry", "Intervention", "Tier", "Problem", "Metrics", "Extraction Model"])
        for r in records:
            mc = session.query(MetricRecord).filter_by(intervention_id=r.id).count()
            ind = ", ".join(r.organization_industry) if r.organization_industry else ""
            w.writerow([r.organization_name, ind, r.intervention_title, r.review_status, r.problem_statement[:60] if r.problem_statement else "", mc, r.extraction_model or ""])
    print(f"\n  CSV: {desk}")
    session.close()


if __name__ == "__main__":
    main()
