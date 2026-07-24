import time
import uuid
import hashlib
from pathlib import Path
from datetime import datetime

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag
from compass_collector.scraper.search.query_generator import SearchQueryGenerator
from compass_collector.scraper.sources.web_search import WebSearchScraper, RSSFeedScraper
from compass_collector.scraper.sources.arxiv_scraper import ArxivScraper
from compass_collector.scraper.extraction.field_extractor import FieldExtractor
from compass_collector.config.settings import DATA_DIR, RAW_DIR, EXPORTS_DIR


class ScaleCollectionPipeline:

    def __init__(self):
        self.query_gen = SearchQueryGenerator()
        self.web_search = WebSearchScraper()
        self.rss_scraper = RSSFeedScraper()
        self.arxiv = ArxivScraper()
        self.field_extractor = FieldExtractor()
        self.raw_dir = RAW_DIR

        self.stats = {
            "queries_generated": 0, "urls_discovered": 0,
            "urls_fetched": 0, "urls_failed": 0,
            "interventions_detected": 0, "interventions_complete": 0,
            "metrics_extracted": 0,
        }

    def run(self, target_records: int = 2000, max_queries: int = 200):
        print(f"=== Scale Collection Pipeline ===")
        print(f"Target: {target_records} records, Max queries: {max_queries}\n")

        init_db()

        print("Phase 1: Generating search queries...")
        queries = self._generate_queries(max_queries)
        self.stats["queries_generated"] = len(queries)
        print(f"  Generated {len(queries)} queries\n")

        print("Phase 2: Discovering URLs...")
        urls = self._discover_urls(queries)
        self.stats["urls_discovered"] = len(urls)
        print(f"  Discovered {len(urls)} URLs\n")

        print("Phase 3: Fetching and extracting...")
        interventions = self._fetch_and_extract(urls)
        self.stats["interventions_detected"] = len(interventions)
        print(f"  Extracted {len(interventions)} interventions\n")

        print("Phase 4: Validating completeness...")
        complete = self._validate_completeness()
        self.stats["interventions_complete"] = complete
        print(f"  {complete}/{len(interventions)} complete\n")

        print("Phase 5: Exporting...")
        self._export()

        print(f"\n=== Collection Complete ===")
        for k, v in self.stats.items():
            print(f"  {k}: {v}")
        return self.stats

    def _generate_queries(self, max_queries: int) -> list[dict]:
        all_q = self.query_gen.generate_all()
        fail_q = self.query_gen.generate_failures()
        return (all_q + fail_q)[:max_queries]

    def _discover_urls(self, queries: list[dict]) -> list[dict]:
        discovered = []
        seen = set()

        # Phase 2a: RSS feeds (fastest, most reliable)
        print("  Fetching RSS feeds...")
        try:
            rss_entries = self.rss_scraper.fetch_all_feeds(max_per_feed=20)
            for r in rss_entries:
                url = r.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    r["search_query"] = "rss_feed"
                    discovered.append(r)
            print(f"    RSS feeds: {len(rss_entries)} entries, {len(discovered)} unique URLs")
        except Exception as e:
            print(f"    RSS feeds failed: {e}")

        # Phase 2b: Arxiv API (fast, structured)
        print("  Fetching arxiv papers...")
        try:
            arxiv_papers = self.arxiv.search_by_keywords(max_per_keyword=10)
            for p in arxiv_papers:
                url = p.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    p["search_query"] = "arxiv"
                    p["problem"] = "research"
                    discovered.append(p)
            print(f"    Arxiv: {len(arxiv_papers)} papers, {len(discovered)} total URLs")
        except Exception as e:
            print(f"    Arxiv failed: {e}")

        # Phase 2c: Direct source scraping (known case study repositories)
        print("  Scraping direct sources...")
        try:
            from compass_collector.scraper.sources.direct_sources import DirectSourceScraper
            direct = DirectSourceScraper()
            for source in direct.SOURCES:
                try:
                    soup = direct.fetch_soup(source["url"], timeout=10)
                    links = direct.extract_links(soup, source["url"])
                    case_links = [
                        l for l in links
                        if any(kw in l.lower() for kw in [
                            "case", "story", "success", "customer", "study"
                        ])
                    ][:5]
                    for link in case_links:
                        if link and link not in seen:
                            seen.add(link)
                            discovered.append({
                                "url": link,
                                "title": source["name"],
                                "snippet": source.get("name", ""),
                                "search_query": "direct_source",
                                "problem": None,
                                "intervention_type": None,
                            })
                    print(f"    {source['name']}: {len(case_links)} links")
                except Exception as e:
                    pass
            print(f"    Direct sources: {len(discovered)} total URLs")
        except Exception as e:
            print(f"    Direct sources failed: {e}")

        # Phase 2d: Bing search (fallback, with timeout)
        print("  Bing search (fallback)...")
        bing_attempts = 0
        for q in queries[:20]:
            if len(discovered) >= 500:
                break
            bing_attempts += 1
            try:
                results = self.web_search.bing_search(q["query"], max_results=5)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen:
                        seen.add(url)
                        r["search_query"] = q["query"]
                        r["problem"] = q.get("problem")
                        r["intervention_type"] = q.get("intervention")
                        discovered.append(r)
            except Exception:
                pass
        print(f"    Bing: {bing_attempts} queries, {len(discovered)} total URLs")

        print(f"\n  Total unique URLs discovered: {len(discovered)}")
        return discovered

    def _fetch_and_extract(self, urls: list[dict]) -> list:
        interventions = []
        for item in urls:
            if len(interventions) >= 2000:
                break
            url = item.get("url", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            if not url:
                continue
            try:
                text = self._fetch_text(url)
                if not text or len(text) < 200:
                    text = snippet
                fields = self.field_extractor.extract_all(text)
                inv = self._create_intervention(url, title, text, fields, item)
                if inv:
                    interventions.append(inv)
                    self.stats["urls_fetched"] += 1
            except Exception as e:
                self.stats["urls_failed"] += 1
                if self.stats["urls_failed"] <= 3:
                    print(f"  Failed {url[:50]}: {e}")
        return interventions

    def _fetch_text(self, url: str) -> str:
        try:
            # Resolve redirect URLs (DuckDuckGo, Bing, etc.)
            if "duckduckgo.com/l/" in url or "bing.com/ck/a" in url:
                try:
                    resp = self.web_search.fetch(url, timeout=10)
                    url = resp.url
                except Exception:
                    return ""
            if url.startswith("//"):
                url = "https:" + url
            soup = self.web_search.fetch_soup(url, timeout=15)
            return self.web_search.extract_text(soup)
        except Exception:
            return ""

    def _create_intervention(self, url: str, title: str,
                              text: str, fields: dict, item: dict) -> InterventionRecord:
        session = get_session()
        try:
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            existing = session.query(InterventionRecord).filter_by(
                intervention_title=title[:200]
            ).first()
            if existing:
                return existing

            doc = Document(
                id=str(uuid.uuid4()),
                url=url,
                canonical_url=url,
                title=title[:500],
                content_hash=content_hash,
                document_type="html",
                crawl_status="success",
                clean_text_path=str(self.raw_dir / "clean" / f"{content_hash[:16]}.txt"),
                retrieved_at=datetime.utcnow()
            )
            session.add(doc)

            # Save clean text to file
            clean_path = self.raw_dir / "clean" / f"{content_hash[:16]}.txt"
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            clean_path.write_text(text)

            families = [f for f, kws in self.field_extractor.INDUSTRY_KEYWORDS.items()
                        if any(kw in text.lower() for kw in kws)]
            if not families:
                families = ["unknown"]

            inv = InterventionRecord(
                id=str(uuid.uuid4()),
                source_id="",
                document_id=doc.id,
                organization_name=fields.get("organization_name"),
                organization_anonymized=False,
                organization_industry=fields.get("organization_industry", []),
                organization_geography=[],
                organization_employee_count=fields.get("organization_employee_count"),
                organization_employee_band=fields.get("organization_employee_band"),
                problem_business_function=fields.get("problem_business_function", []),
                problem_statement=fields.get("problem_statement", ""),
                problem_categories=[item.get("problem")] if item.get("problem") else [],
                intervention_title=title[:500],
                intervention_families=families,
                intervention_description=text[:5000],
                intervention_implementation_cost=fields.get("intervention_implementation_cost"),
                intervention_implementation_time_value=fields.get("intervention_implementation_time_value"),
                intervention_implementation_time_unit=fields.get("intervention_implementation_time_unit"),
                intervention_measurement_period_value=fields.get("measurement_period"),
                intervention_software=fields.get("software", []),
                intervention_teams_involved=fields.get("teams_involved", []),
                result_status=self._detect_status(text),
                success_factors=fields.get("success_factors", []),
                failure_conditions=fields.get("failure_conditions", []),
                has_baseline=fields.get("has_baseline", False),
                has_post_measurement=fields.get("has_post_measurement", False),
                has_control_group=fields.get("has_control_group", False),
                sample_size=fields.get("sample_size"),
                independently_verified=fields.get("independently_verified", False),
                vendor_reported=fields.get("vendor_reported", False),
                extractor="field_extractor_v2",
                extracted_at=datetime.utcnow(),
            )
            session.add(inv)
            session.flush()

            for flag in self._gen_flags(fields, text):
                session.add(QualityFlag(
                    id=str(uuid.uuid4()),
                    intervention_id=inv.id,
                    flag_name=flag
                ))

            session.commit()
            return inv
        finally:
            session.close()

    def _detect_status(self, text: str) -> str:
        tl = text.lower()
        if any(kw in tl for kw in ["failed", "abandoned", "cancelled", "unsuccessful"]):
            return "failed"
        if any(kw in tl for kw in ["success", "improved", "exceeded", "achieved"]):
            return "successful"
        if any(kw in tl for kw in ["partial", "mixed", "limited"]):
            return "partial"
        if any(kw in tl for kw in ["pilot", "trial", "experiment"]):
            return "ongoing"
        return "unknown"

    def _gen_flags(self, fields: dict, text: str) -> list[str]:
        flags = []
        if not fields.get("organization_name"):
            flags.append("missing_organization")
        if not fields.get("intervention_implementation_cost"):
            flags.append("missing_implementation_cost")
        if not fields.get("has_baseline"):
            flags.append("no_baseline")
        if fields.get("vendor_reported"):
            flags.append("vendor_reported")
        if not fields.get("sample_size"):
            flags.append("no_sample_size")
        if "projected" in text.lower():
            flags.append("projected_rather_than_observed")
        return flags

    def _validate_completeness(self) -> int:
        session = get_session()
        try:
            complete = 0
            for inv in session.query(InterventionRecord).all():
                has_org = inv.organization_name is not None
                has_cost = inv.intervention_implementation_cost is not None
                has_time = inv.intervention_implementation_time_value is not None
                has_base = inv.has_baseline
                has_post = inv.has_post_measurement
                has_metrics = session.query(MetricRecord).filter_by(intervention_id=inv.id).count() > 0
                if sum([has_org, has_cost, has_time, has_base, has_post, has_metrics]) >= 5:
                    complete += 1
            return complete
        finally:
            session.close()

    def _export(self):
        from compass_collector.export.formats import ExportEngine
        ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
