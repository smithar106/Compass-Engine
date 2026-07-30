#!/usr/bin/env python3
"""Evidence collection using OpenCLI browser bridge for JS-rendered pages.

Usage:
    export DEEPSEEK_API_KEY=sk-...
    python scripts/run_collection.py --api-key "$DEEPSEEK_API_KEY"

Requires: opencli browser bridge extension installed and connected.
Test with: opencli doctor
"""

import sys, os, json, time, uuid, hashlib, subprocess, re, logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

logger = logging.getLogger("collect")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass_collector.database import get_session, init_db
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.engine.crawl import CrawlEngine
from compass_collector.extraction_llm.orchestrator import ExtractionOrchestrator
from sqlalchemy import func


# === SOURCE URLs ===
# Discovered URLs file from discover_sources.py
DISCOVERED_URLS_FILE = Path(__file__).resolve().parent.parent / "data" / "registry" / "discovered_urls.json"

def load_discovered_urls() -> list[str]:
    """Load validated case study URLs from the discovery system."""
    path = DISCOVERED_URLS_FILE
    if not path.exists():
        logger.warning(f"No discovered URLs at {path}. Run discover_sources.py --discover first.")
        return []
    with open(path) as f:
        data = json.load(f)
    urls = []
    for source_name, source_data in data.items():
        for entry in source_data.get("urls", []):
            if isinstance(entry, str):
                urls.append(entry)
            elif isinstance(entry, dict):
                u = entry.get("url") or entry.get("final_url", "")
                if u: urls.append(u)
    # Deduplicate and filter
    seen = set()
    filtered = []
    for u in urls:
        base = u.split("#")[0].split("?")[0]
        if base in seen:
            continue
        seen.add(base)
        # Keep URLs that look like individual case studies
        if any(p in u for p in ["/case-studies/", "/customers/", "/automation-case-studies/", "/reports/", "/stories/", "/client-stories/"]):
            # Exclude listing pages (ends with / or has only the base pattern)
            if base.rstrip("/").endswith("/customers") or base.endswith("/customers/"):
                continue
            filtered.append(base)
    return filtered


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


def discover_case_study_urls(listing_url: str) -> list[str]:
    """Scrape a listing page to find individual case study URLs."""
    try:
        import urllib.request
        req = urllib.request.Request(listing_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/automation-case-studies/" in href and href not in ("/resources/automation-case-studies",):
                full = urljoin("https://www.uipath.com", href)
                urls.add(full)
        return sorted(urls)[:30]
    except Exception as e:
        logger.warning(f"  Failed to discover URLs from {listing_url}: {e}")
        return []


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
    parser.add_argument("--max-urls", type=int, default=200, help="Max URLs to fetch (default 200)")
    parser.add_argument("--no-extract", action="store_true", help="Skip LLM extraction")
    parser.add_argument("--re-extract", action="store_true", help="Re-extract all documents (not just unprocessed)")
    args = parser.parse_args()

    init_db()
    session = get_session()
    existing_urls = set(u for (u,) in session.query(Document.url).all() if u)

    # === STEP 0: LOAD DISCOVERED URLs ===
    print("\n" + "=" * 60)
    print("STEP 0: Loading discovered case study URLs")
    print("=" * 60)
    all_urls = load_discovered_urls()
    print(f"  Discovered URLs: {len(all_urls)}")
    print(f"  New or existing URLs: {len(all_urls)}")
    print(f"  Previously fetched: {sum(1 for u in all_urls if u in existing_urls)}")

    # === STEP 1: FETCH NEW PAGES ===
    to_fetch = [u for u in all_urls if u not in existing_urls][:args.max_urls]
    print(f"\n  New URLs to fetch: {len(to_fetch)}")

    print("\n" + "=" * 60)
    print("STEP 1: Fetching pages")
    print("=" * 60)

    new_docs = 0
    for i, url in enumerate(to_fetch):
        print(f"  [{i+1}/{len(to_fetch)}] Fetching: {url[:70]}...")
        text, method = fetch_url(url)
        if text and len(text) > 500:
            doc = save_document(session, url, text, method or "unknown")
            new_docs += 1
            print(f"    OK ({method}, {len(text)} chars)")
        else:
            print(f"    FAILED ({method})")
        time.sleep(1.5)

    session.commit()
    print(f"\n  Fetched {new_docs} new documents")

    # === STEP 2: LLM EXTRACTION ===
    if not args.no_extract and args.api_key:
        print("\n" + "=" * 60)
        print("STEP 2: LLM Extraction (improved prompt)")
        print("=" * 60)

        if args.re_extract:
            # Delete old low-quality extractions
            old = session.query(InterventionRecord).filter(InterventionRecord.extractor.in_(["llm_extraction", "llm_extraction_v2"])).all()
            for rec in old:
                session.query(MetricRecord).filter_by(intervention_id=rec.id).delete()
                session.delete(rec)
            session.commit()
            print(f"  Removed {len(old)} old extraction records for re-extraction")
            docs = session.query(Document).filter(Document.cleaned_text.isnot(None), Document.crawl_status == "success").all()
        else:
            processed_ids = set()
            for rid, in session.query(InterventionRecord.document_id).filter(InterventionRecord.document_id.isnot(None)).all():
                if rid: processed_ids.add(rid)
            docs = session.query(Document).filter(
                Document.cleaned_text.isnot(None),
                Document.crawl_status == "success",
                ~Document.id.in_(processed_ids) if processed_ids else True
            ).limit(100).all()

        print(f"  Documents to extract: {len(docs)}")
        if docs:
            orch = ExtractionOrchestrator()
            orch.set_api_key(args.api_key)
            doc_list = [{"id": d.id, "title": d.title or "", "url": d.url or "", "text": d.cleaned_text or "", "source_type": "web"} for d in docs]
            results, counts = orch.run_relevance_filter(doc_list)
            print(f"  Relevance: {counts}")
            relevant_ids = set(d["record_id"] for d in results if d["classification"] in ("high_relevance", "possible_relevance"))
            extraction_docs = [d for d in doc_list if d.get("id") in relevant_ids]
            print(f"  Documents for extraction: {len(extraction_docs)}")
            if extraction_docs:
                extracted = orch.run_extraction(extraction_docs)
                validated = orch.validator.validate_batch(extracted) if hasattr(orch.validator, 'validate_batch') else []
                # Save from ORIGINAL extraction results (validator strips the data)
                for ext in extracted:
                    data = ext.get("extraction") or ext
                    if not isinstance(data, dict) or not data.get("organization_name"):
                        continue
                    rid = str(uuid.uuid4())
                    industry = data.get("organization_industry") or data.get("industry") or []
                    if isinstance(industry, str): industry = [industry]
                    bfunc = data.get("business_function") or ""
                    outcome_metrics = data.get("outcomes") or data.get("metrics") or []
                    duration = data.get("implementation_duration_value") or 0
                    eq = data.get("evidence_quality") or {}
                    intervention = InterventionRecord(
                        id=rid, source_id=f"llm-{rid[:8]}",
                        organization_name=data.get("organization_name", ""),
                        organization_industry=industry,
                        organization_employee_count=data.get("organization_employee_count"),
                        problem_business_function=[bfunc] if bfunc else [],
                        problem_statement=str(data.get("business_problem") or data.get("problem", ""))[:500],
                        intervention_title=str(data.get("intervention_title") or data.get("intervention", ""))[:200],
                            intervention_families=[data.get("intervention_category", "").lower()] if data.get("intervention_category") else [],
                            intervention_vendors=data.get("intervention_vendors") or [],
                            intervention_implementation_time_value=duration if duration else None,
                            intervention_implementation_time_unit=data.get("implementation_duration_unit"),
                            has_baseline=bool(data.get("baseline_description")),
                            has_post_measurement=True,
                            independently_verified=eq.get("independently_verified", False),
                            vendor_reported=eq.get("is_vendor_reported", False),
                            extraction_model="deepseek-v4-flash", extractor="llm_extraction_v2",
                            extracted_at=datetime.now(timezone.utc), review_status="pending")
                    session.add(intervention)
                    for m in outcome_metrics:
                        session.add(MetricRecord(id=str(uuid.uuid4()), intervention_id=rid,
                            source_id=intervention.source_id, metric_name=m.get("name", "") or m.get("metric_name", ""),
                            metric_category=m.get("category", ""), absolute_change=m.get("absolute_change"),
                            percentage_change=m.get("percentage_change"), unit=m.get("unit", ""),
                            reported_text=m.get("reported_text", m.get("metric_name", "")), value_type="reported"))
                session.commit()
                saved_count = sum(1 for ext in extracted if isinstance(ext.get("extraction") or ext, dict) and (ext.get("extraction") or ext).get("organization_name"))
                print(f"  Extracted {saved_count} records from {len(extracted)} extractions")

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
