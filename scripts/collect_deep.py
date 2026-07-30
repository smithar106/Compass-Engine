#!/usr/bin/env python3
"""Deep evidence collector — uses OpenCLI browser to fetch JS-rendered case study pages.

Many vendor case studies (Oracle, NVIDIA, Accenture) are JS-rendered and return
empty shells to plain HTTP requests. This collector uses OpenCLI's browser bridge
to render pages fully, then extracts the content for LLM processing.

Usage:
    ./venv/bin/python scripts/collect_deep.py --source oracle --max 50
    ./venv/bin/python scripts/collect_deep.py --all --max 200
    ./venv/bin/python scripts/collect_deep.py --report
"""

import sys, os, json, time, uuid, hashlib, subprocess, logging, re
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("deep-collect")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compass_collector.database import get_session, init_db
from compass_collector.models.document import Document
from compass_collector.config.settings import REGISTRY_DIR, CACHE_DIR

PROFILE = os.environ.get("OPENCLI_PROFILE", "2dsmkwnt")
OPENCLI_TIMEOUT = 45


def opencli_fetch(url: str) -> str | None:
    """Fetch page content using OpenCLI browser (handles JS rendering)."""
    try:
        subprocess.run(["opencli", "browser", PROFILE, "close"], capture_output=True, text=True, timeout=10)
    except: pass

    try:
        r = subprocess.run(["opencli", "browser", PROFILE, "open", url], capture_output=True, text=True, timeout=OPENCLI_TIMEOUT)
        if r.returncode != 0:
            return None
        time.sleep(5)
        r2 = subprocess.run(["opencli", "browser", PROFILE, "extract"], capture_output=True, text=True, timeout=OPENCLI_TIMEOUT)
        if r2.returncode == 0 and len(r2.stdout) > 200:
            try:
                d = json.loads(r2.stdout)
                return d.get("content", "") or d.get("text", "") or r2.stdout
            except:
                return r2.stdout
        return None
    except subprocess.TimeoutExpired:
        return None


def load_discovered_urls(source_name: str = None) -> list[str]:
    """Load discovered URLs, optionally filtered by source."""
    path = REGISTRY_DIR / "discovered_urls.json"
    if not path.exists():
        logger.error("No discovered URLs. Run discover_sources.py first.")
        return []
    import json
    with open(path) as f:
        data = json.load(f)
    urls = []
    for src, sd in data.items():
        if source_name and src != source_name:
            continue
        for u in sd.get("urls", []):
            if isinstance(u, dict): u = u.get("url") or u.get("final_url", "")
            if not u: continue
            base = u.split("#")[0].split("?")[0].rstrip("/")
            # Skip explicit listing pages only
            if re.search(r'/customers/?$', base) or re.search(r'/case-studies/?$', base):
                continue
            # Skip anchor-only and search pages
            if base.count("/") <= 3:  # root domain only
                continue
            urls.append(base)
    return list(set(urls))


def fetch_and_save(url: str, session) -> bool:
    """Fetch a URL via OpenCLI and save to DB. Returns True if saved."""
    existing = session.query(Document).filter(Document.url == url).first()
    if existing:
        return False

    text = opencli_fetch(url)
    if not text or len(text) < 300:
        return False

    doc = Document(
        id=str(uuid.uuid4()), url=url, title=url.split("/")[-1][:80],
        retrieved_at=datetime.now(timezone.utc), document_type="web",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        cleaned_text=text[:100000], crawl_status="success", parser_version="3.0.0",
    )
    session.add(doc)
    return True


def run_collect(args):
    """Main collection loop."""
    init_db()
    session = get_session()

    sources = [args.source] if args.source else ["uipath", "ibm", "oracle", "nvidia", "accenture", "nao_uk"]
    total_fetched = 0

    for src in sources:
        urls = load_discovered_urls(src)
        if not urls:
            logger.info(f"  {src}: no URLs to process")
            continue

        # Limit
        urls = urls[:args.max]
        logger.info(f"\n--- {src}: {len(urls)} URLs ---")

        for i, url in enumerate(urls):
            saved = fetch_and_save(url, session)
            if saved:
                total_fetched += 1
                logger.info(f"  [{i+1}/{len(urls)}] ✅ {url[:70]}")
            else:
                logger.info(f"  [{i+1}/{len(urls)}] ⏭ {url[:60]}")

            session.commit()
            time.sleep(2)

    total_docs = session.query(Document).count()
    logger.info(f"\n=== Done. Fetched {total_fetched} new docs. Total DB: {total_docs} ===")
    session.close()


def run_report():
    """Report current state."""
    from compass_collector.models.intervention import InterventionRecord, MetricRecord
    from sqlalchemy import func

    init_db()
    session = get_session()
    total_docs = session.query(Document).count()
    total_recs = session.query(InterventionRecord).count()
    ready = session.query(InterventionRecord.id).filter(
        InterventionRecord.organization_name.isnot(None),
        InterventionRecord.intervention_title != "",
        InterventionRecord.id.in_(session.query(MetricRecord.intervention_id).distinct())
    ).count()
    tiers = dict(session.query(InterventionRecord.review_status, func.count(InterventionRecord.id)).group_by(InterventionRecord.review_status).all())

    print("\n" + "=" * 60)
    print("DEEP COLLECTOR REPORT")
    print("=" * 60)
    print(f"  Documents:              {total_docs}")
    print(f"  Total implementations:  {total_recs}")
    print(f"  Recommendation-ready:   {ready}")
    for t in ["gold", "silver", "bronze"]:
        print(f"    {t}: {tiers.get(t, 0)}")
    print(f"  Total gap to 900: {max(0, 900 - total_recs)}")
    print("=" * 60)
    session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Specific source to collect")
    parser.add_argument("--all", action="store_true", help="Collect all sources")
    parser.add_argument("--max", type=int, default=50, help="Max URLs per source")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        run_report()
    elif args.all or args.source:
        run_collect(args)
    else:
        parser.print_help()
