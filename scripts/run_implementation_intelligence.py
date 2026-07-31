"""Implementation Intelligence Campaign Runner.

Targeted extraction of implementation-rich evidence. Measures success
by implementation field density, not document count or Silver count.

Usage:
  ./venv/bin/python3 scripts/run_implementation_intelligence.py --campaign invoice_finance --limit 30
  ./venv/bin/python3 scripts/run_implementation_intelligence.py --all --batch-size 50
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.database import get_session, engine
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.extraction_llm.llm_extractor import LLM_EXTRACTION_PROMPT
from sqlalchemy import text, func

def _get_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY", "")
    if k and k not in ("YOUR_KEY_HERE", "", " "):
        return k
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if k and k not in ("YOUR_KEY_HERE", "", " "):
        return k
    return "sk-4c4a146881a346338565063341319566"

KEY = _get_key()
API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

IMPLEMENTATION_FIELDS = [
    "pilot_structure",
    "rollout_strategy",
    "implementation_partner",
    "executive_sponsor",
    "implementation_team_structure",
    "intervention_vendors",
    "governance_model",
    "change_management",
    "training_approach",
    "adoption_approach",
    "success_criteria",
    "lessons_learned",
    "implementation_duration_value",
    "budget_range",
    "implementation_pattern",
]

FOCUSED_CAMPAIGNS = {
    "invoice_finance": {
        "name": "Invoice & Finance Automation",
        "searches": [
            "AP automation case study implementation rollout results",
            "invoice processing RPA implementation pilot lessons learned",
            "finance process automation governance change management",
            "accounts payable AI implementation partner deployment strategy",
            "financial close automation rollout training adoption",
        ],
        "source_urls": [
            "https://www.uipath.com/resources/automation-case-studies?industry=financial-services",
            "https://aws.amazon.com/solutions/case-studies/financial-services/",
            "https://cloud.google.com/customers/#/finance",
            "https://www.servicenow.com/success/finance.html",
        ],
    },
    "customer_support": {
        "name": "Customer Support & Triage",
        "searches": [
            "customer support AI implementation case study rollout metrics",
            "contact center automation deployment governance lessons learned",
            "chatbot implementation pilot enterprise rollout change management",
            "support ticket triage automation partner implementation results",
            "customer service AI agent deployment strategy adoption training",
        ],
        "source_urls": [
            "https://cloud.google.com/customers/#/retail",
            "https://aws.amazon.com/solutions/case-studies/contact-center/",
            "https://www.salesforce.com/customer-success-stories/service/",
            "https://www.servicenow.com/success/customer-service.html",
        ],
    },
    "customer_onboarding": {
        "name": "Customer Onboarding",
        "searches": [
            "customer onboarding automation implementation case study rollout",
            "KYC onboarding digital transformation governance lessons learned",
            "client onboarding workflow automation pilot enterprise deployment",
            "account opening automation partner implementation change management",
            "customer identity verification implementation strategy adoption",
        ],
        "source_urls": [
            "https://aws.amazon.com/solutions/case-studies/financial-services/",
            "https://cloud.google.com/customers/#/financial-services",
            "https://www.uipath.com/resources/automation-case-studies?industry=banking",
        ],
    },
    "knowledge_management": {
        "name": "Knowledge Management",
        "searches": [
            "enterprise knowledge management AI implementation case study deployment",
            "knowledge base automation internal search implementation pilot metrics",
            "information retrieval AI enterprise rollout governance change management",
            "corporate wiki knowledge graph implementation partner lessons learned",
            "document intelligence AI implementation training adoption strategy",
        ],
        "source_urls": [
            "https://cloud.google.com/customers/#/technology",
            "https://aws.amazon.com/solutions/case-studies/data-analytics/",
            "https://www.databricks.com/customers",
            "https://www.snowflake.com/en/customers/",
        ],
    },
    "contract_document": {
        "name": "Contract & Document Processing",
        "searches": [
            "contract review AI implementation case study rollout metrics adoption",
            "legal document automation enterprise deployment governance partner",
            "contract lifecycle management implementation pilot lessons learned",
            "document processing AI OCR implementation strategy change management",
            "legal AI implementation enterprise rollout training validation gate",
        ],
        "source_urls": [
            "https://aws.amazon.com/solutions/case-studies/government/",
            "https://cloud.google.com/customers/#/media",
            "https://www.uipath.com/resources/automation-case-studies?industry=legal",
        ],
    },
}


@dataclass
class BatchReport:
    campaign: str
    batch_number: int
    fetched: int = 0
    parsed: int = 0
    extracted: int = 0
    saved: int = 0
    duplicates: int = 0
    rich_count: int = 0
    usable_count: int = 0
    thin_count: int = 0
    field_fill_rates: dict = field(default_factory=dict)
    source_resolvable: int = 0
    cost_estimate: str = ""
    benchmark_delta: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def print(self):
        print(f"\n{'='*60}")
        print(f"BATCH REPORT: {self.campaign} (batch #{self.batch_number})")
        print(f"{'='*60}")
        print(f"  Fetched:  {self.fetched}")
        print(f"  Parsed:   {self.parsed}")
        print(f"  Extracted:{self.extracted}")
        print(f"  Saved:    {self.saved}")
        print(f"  Duplicates:{self.duplicates}")
        print(f"  Rich:     {self.rich_count} (4+ fields)")
        print(f"  Usable:   {self.usable_count} (2-3 fields)")
        print(f"  Thin:     {self.thin_count} (0-1 fields)")
        print(f"  Source-resolvable: {self.source_resolvable}")
        print(f"  Time:     {self.elapsed_seconds:.1f}s")
        if self.cost_estimate:
            print(f"  Cost:     {self.cost_estimate}")
        print(f"\n  Field fill rates:")
        for f, rate in sorted(self.field_fill_rates.items(), key=lambda x: -x[1]):
            bar = "█" * int(rate * 20)
            print(f"    {f:<35} {rate:.0%} {bar}")
        if self.benchmark_delta:
            print(f"\n  Benchmark delta:")
            for k, v in self.benchmark_delta.items():
                print(f"    {k}: {v}")


def fetch_with_wayback(url: str) -> tuple[str, str]:
    """Fetch URL with Wayback Machine fallback."""
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    for attempt in ["direct", "wayback"]:
        try:
            if attempt == "wayback":
                fetch_url = f"https://web.archive.org/web/2025/{url}"
            else:
                fetch_url = url
            r = subprocess.run(
                ["curl", "-sL", "-A", ua, "--max-time", "30", fetch_url],
                capture_output=True, text=True, timeout=35,
            )
            if len(r.stdout) > 500 and r.returncode == 0:
                return r.stdout, attempt
        except Exception:
            pass
        time.sleep(1)
    return "", "failed"


def parse_html(html: str) -> str:
    """Extract clean text from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:500000]


def call_llm_implementation(text: str) -> dict:
    """Call DeepSeek with implementation-focused prompt."""
    import urllib.request
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": LLM_EXTRACTION_PROMPT + "\n\n" + text[:12000]}],
        "temperature": 0.0,
        "max_tokens": 8000,
    }).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    raw = json.loads(resp.read())["choices"][0]["message"]["content"]
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def capture_field_provenance(parsed: dict, doc: Document) -> list[dict]:
    """For each implementation field in the parsed output, capture source provenance."""
    provenance = []
    text = doc.cleaned_text or ""

    for field in IMPLEMENTATION_FIELDS:
        val = parsed.get(field)
        if val is None or (isinstance(val, str) and len(val.strip()) < 5) or (isinstance(val, list) and len(val) == 0):
            continue

        supporting = ""
        if isinstance(val, str) and val.strip():
            idx = text.lower().find(val.lower()[:50])
            if idx >= 0:
                supporting = text[max(0, idx - 100): idx + len(val[:200]) + 100]
        elif isinstance(val, list) and val:
            for item in val[:1]:
                idx = text.lower().find(str(item).lower()[:50])
                if idx >= 0:
                    supporting = text[max(0, idx - 100): idx + len(str(item)[:200]) + 100]
                    break

        explicit = bool(supporting and len(supporting) > 20)

        provenance.append({
            "field_name": field,
            "value": val[:500] if isinstance(val, str) else val,
            "supporting_text": supporting[:1000] if supporting else "",
            "source_id": doc.id,
            "source_url": doc.url or "",
            "source_section": "",
            "extraction_confidence": "medium",
            "explicit": explicit,
        })

    return provenance


def classify_richness(provenance: list[dict]) -> str:
    """Classify implementation richness from field provenance."""
    fields = set(p.get("field_name") for p in provenance if p.get("explicit"))
    count = len(fields)
    if count >= 4:
        return "rich"
    elif count >= 2:
        return "usable"
    return "thin"


def save_implementation_record(doc: Document, parsed: dict, provenance: list[dict]) -> str | None:
    """Save a provenance-traced implementation record."""
    if parsed.get("evidence_tier") == "rejected":
        return None
    org = parsed.get("organization_name")
    if not org:
        return None

    eq = parsed.get("evidence_quality", {})
    ob = parsed.get("outcome_block", {})
    richness = classify_richness(provenance)
    rid = str(uuid.uuid4())

    session = get_session()
    try:
        rec = InterventionRecord(
            id=rid,
            source_id=f"impl-{rid[:8]}",
            document_id=doc.id,
            organization_name=org,
            organization_industry=[parsed.get("organization_industry")] if parsed.get("organization_industry") else [],
            problem_statement=str(parsed.get("business_problem", ""))[:500] or f"Operational transformation at {org}",
            problem_baseline_description=str(parsed.get("baseline_description", ""))[:2000],
            intervention_title=str(parsed.get("intervention_title", ""))[:200],
            intervention_families=[parsed.get("intervention_category", "").lower()] if parsed.get("intervention_category") else [],
            intervention_vendors=parsed.get("intervention_vendors") or [],
            independently_verified=bool(eq.get("independently_verified")),
            vendor_reported=bool(eq.get("is_vendor_reported")),
            has_baseline=bool(ob.get("baseline_metric")),
            has_post_measurement=bool(ob.get("post_metric")),
            measurement_method=str(ob.get("measurement_method", ""))[:500],
            extraction_model=MODEL,
            extractor="implementation_intelligence_v1",
            extracted_at=datetime.now(timezone.utc),
            review_status="pending",
            implementation_provenance=eq.get("implementation_provenance", "vendor_documented"),
            outcome_provenance=eq.get("outcome_provenance"),
            implementation_detail_score=eq.get("implementation_detail_score"),
            outcome_credibility_score=eq.get("outcome_credibility_score"),
            methodology_detail_score=eq.get("methodology_detail_score"),
            operational_insight_score=eq.get("operational_insight_score"),
            outcome_block=ob,
            source_type=ob.get("source_type", "vendor_case_study"),
            evidence_level=ob.get("evidence_level"),
            # Implementation Intelligence
            executive_sponsor=str(parsed.get("executive_sponsor", ""))[:200],
            pilot_structure=str(parsed.get("pilot_structure", ""))[:2000],
            training_approach=str(parsed.get("training_approach", ""))[:2000],
            adoption_approach=str(parsed.get("adoption_approach", ""))[:2000],
            implementation_team_structure=str(parsed.get("implementation_team_structure", ""))[:2000],
            budget_range=str(parsed.get("budget_range", ""))[:100],
            key_decision_makers=parsed.get("key_decision_makers") or [],
            success_criteria=parsed.get("success_criteria") or [],
            implementation_partner=parsed.get("implementation_partner") or [],
            implementation_pattern=parsed.get("implementation_pattern") or [],
            lessons_learned=parsed.get("lessons_learned") or [],
            change_management=str(parsed.get("change_management", ""))[:2000],
            rollout_strategy=str(parsed.get("rollout_strategy", ""))[:2000],
            governance_model=str(parsed.get("governance_model", ""))[:1000],
            implementation_field_provenance=provenance,
            implementation_richness=richness,
        )
        session.add(rec)
        for m in parsed.get("outcomes") or []:
            session.add(MetricRecord(
                id=str(uuid.uuid4()), intervention_id=rid, source_id=rec.source_id,
                metric_name=m.get("metric_name", ""), metric_category=m.get("category", ""),
                baseline_value=m.get("baseline_value"), post_value=m.get("post_value"),
                absolute_change=m.get("absolute_change"), percentage_change=m.get("percentage_change"),
                unit=m.get("unit", ""), reported_text=m.get("source_passage", "")[:1000],
                value_type=m.get("value_type", "reported"),
            ))
        session.commit()
        return rid
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()


def run_campaign(campaign_key: str, limit: int = 30) -> BatchReport:
    """Run a focused implementation intelligence campaign."""
    campaign = FOCUSED_CAMPAIGNS.get(campaign_key)
    if not campaign:
        print(f"Unknown campaign: {campaign_key}")
        return BatchReport(campaign=campaign_key, batch_number=0)

    start = time.time()
    report = BatchReport(campaign=campaign_key, batch_number=1)

    print(f"\n{'='*60}")
    print(f"CAMPAIGN: {campaign['name']}")
    print(f"{'='*60}")

    # Build fetch list: direct URLs + search-based discovery
    urls_to_fetch = list(campaign.get("source_urls", []))

    # Also do web searches for each search term
    for search in campaign.get("searches", [])[:2]:
        try:
            search_url = f"https://lite.duckduckgo.com/lite/?q={search.replace(' ', '+')}"
            r = subprocess.run(
                ["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", "15", search_url],
                capture_output=True, text=True, timeout=20,
            )
            if r.stdout:
                # Parse result links
                from html.parser import HTMLParser
                class LinkParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.urls = []
                    def handle_starttag(self, tag, attrs):
                        if tag == 'a':
                            d = dict(attrs)
                            href = d.get('href', '')
                            if href.startswith('http') and 'duckduckgo' not in href and 'ad.' not in href:
                                self.urls.append(href)
                p = LinkParser()
                p.feed(r.stdout)
                for u in p.urls[:5]:
                    if u not in urls_to_fetch:
                        urls_to_fetch.append(u)
        except Exception:
            pass

    print(f"  Target URLs: {len(urls_to_fetch)}")

    # Process URLs: first fetch listing pages to discover story links
    story_urls = set()
    for url in urls_to_fetch[:limit]:
        try:
            html, method = fetch_with_wayback(url)
            if not html or len(html) < 500:
                continue
            report.fetched += 1
            # Extract story links from listing page
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if not href or href.startswith("#") or href.startswith("javascript"):
                    continue
                if any(kw in href.lower() for kw in ["case-study", "customer", "success", "story", "/customers/", "/resources/automation-case-studies/"]):
                    if href.startswith("/"):
                        # Build absolute URL
                        base = "/".join(url.split("/")[:3])
                        href = base.rstrip("/") + href
                    elif not href.startswith("http"):
                        continue
                    story_urls.add(href)
        except Exception:
            pass

    if not story_urls:
        print(f"  No story links discovered from listing pages — using search results")
        story_urls = set(urls_to_fetch[:limit])

    print(f"  Discovered {len(story_urls)} story URLs, processing up to {limit}")

    # Process individual story pages
    for i, url in enumerate(sorted(story_urls)[:limit]):
        try:
            session = get_session()
            existing = session.query(Document).filter(Document.url == url).first()
            session.close()
            if existing:
                report.duplicates += 1
                continue

            html, method = fetch_with_wayback(url)
            report.fetched += 1

            if not html or len(html) < 500:
                continue

            text = parse_html(html)
            report.parsed += 1

            if len(text) < 300:
                continue

            # Save document
            did = str(uuid.uuid4())
            doc = Document(
                id=did, source_registry_id=f"ii-{did[:6]}", url=url,
                title=url.split("/")[-1].replace("-", " ")[:200] or url[:200],
                document_type="implementation_intelligence",
                cleaned_text=text,
                content_hash=hashlib.sha256(html.encode()).hexdigest()[:32],
                crawl_status="fetched", retrieved_at=datetime.now(timezone.utc),
            )
            session = get_session()
            session.add(doc)
            session.commit()
            session.close()

            # Extract with implementation prompt
            parsed = call_llm_implementation(text)
            report.extracted += 1

            # Capture field provenance
            provenance = capture_field_provenance(parsed, doc)
            richness = classify_richness(provenance)

            # Save record
            rid = save_implementation_record(doc, parsed, provenance)
            if rid:
                report.saved += 1
                if richness == "rich":
                    report.rich_count += 1
                elif richness == "usable":
                    report.usable_count += 1
                else:
                    report.thin_count += 1
                if provenance:
                    report.source_resolvable += 1

        except Exception as e:
            pass
        time.sleep(0.3)

    # Compute field fill rates across the campaign's records
    session = get_session()
    records = session.query(InterventionRecord).filter(
        InterventionRecord.extractor == "implementation_intelligence_v1"
    ).all()
    field_counts = Counter()
    for rec in records:
        for p in (rec.implementation_field_provenance or []):
            field_counts[p.get("field_name", "")] += 1
    total = max(len(records), 1)
    report.field_fill_rates = {f: c / total for f, c in field_counts.most_common()}

    # Count richness distribution
    rich = sum(1 for r in records if r.implementation_richness == "rich")
    usable = sum(1 for r in records if r.implementation_richness == "usable")
    thin = sum(1 for r in records if r.implementation_richness == "thin")
    report.rich_count = rich
    report.usable_count = usable
    report.thin_count = thin
    session.close()

    report.elapsed_seconds = time.time() - start
    total_saved = report.saved if report.saved > 0 else 1
    report.cost_estimate = f"~${report.elapsed_seconds * 0.002:.2f} API (est ${0.002 * total_saved / max(report.elapsed_seconds, 1) * report.saved:.2f}/record)"

    report.print()
    return report


def compute_benchmark_delta() -> dict:
    """Re-run benchmark and return changes."""
    try:
        from compass_collector.analysis.benchmark_evaluator import run as bench_run
        _, stats = bench_run()
        return {
            "precision_top5": stats.get("avg_precision_top5", 0),
            "gold_in_results": stats.get("gold", 0),
            "silver_in_results": stats.get("silver", 0),
            "avg_depth": stats.get("avg_depth", 0),
            "avg_impl_records": stats.get("avg_impl_records", 0),
        }
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", "-c", choices=list(FOCUSED_CAMPAIGNS.keys()), default="invoice_finance")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", "-l", type=int, default=30)
    parser.add_argument("--batch-size", "-b", type=int, default=50)
    args = parser.parse_args()

    # Migrate
    from compass_collector.database import init_db
    from compass_collector.models.intervention import InterventionRecord
    init_db()

    campaigns_to_run = list(FOCUSED_CAMPAIGNS.keys()) if args.all else [args.campaign]

    all_reports = []
    for ck in campaigns_to_run:
        report = run_campaign(ck, limit=args.limit)
        all_reports.append(report)

    # Merge report
    print(f"\n{'='*60}")
    print("ALL CAMPAIGNS SUMMARY")
    print(f"{'='*60}")
    total_saved = sum(r.saved for r in all_reports)
    total_rich = sum(r.rich_count for r in all_reports)
    total_usable = sum(r.usable_count for r in all_reports)
    total_thin = sum(r.thin_count for r in all_reports)
    print(f"  Saved: {total_saved} ({total_rich} rich, {total_usable} usable, {total_thin} thin)")

    # Reclassify new records
    session = get_session()
    from scripts.extract_provenance import classify
    updated = 0
    for rec in session.query(InterventionRecord).filter(
        InterventionRecord.review_status.in_(["pending", "", None])
    ).all():
        rec.review_status = classify(rec, 0)
        updated += 1
    session.commit()
    print(f"  Reclassified: {updated} records")

    # Count implementation richness in graph
    total = session.query(InterventionRecord).count()
    rich = session.query(InterventionRecord).filter(
        InterventionRecord.implementation_richness == "rich"
    ).count()
    usable = session.query(InterventionRecord).filter(
        InterventionRecord.implementation_richness == "usable"
    ).count()
    thin = session.query(InterventionRecord).filter(
        InterventionRecord.implementation_richness == "thin"
    ).count()
    unclassified = total - rich - usable - thin
    session.close()

    print(f"\n  Graph implementation density:")
    print(f"    Rich:   {rich}")
    print(f"    Usable: {usable}")
    print(f"    Thin:   {thin}")
    print(f"    Unclassified: {unclassified}")
    print(f"    Total:  {total}")

    # Benchmark delta
    delta = compute_benchmark_delta()
    if delta:
        print(f"\n  Benchmark delta:")
        for k, v in delta.items():
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
