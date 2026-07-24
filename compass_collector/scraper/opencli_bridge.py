import json
import subprocess
import uuid
import hashlib
import time
from pathlib import Path
from datetime import datetime

from compass_collector.database import init_db, get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, QualityFlag
from compass_collector.models.intervention import MetricRecord
from compass_collector.scraper.extraction.field_extractor import FieldExtractor
from compass_collector.config.settings import RAW_DIR, EXPORTS_DIR


class OpenCLIBridge:

    def __init__(self):
        self.field_extractor = FieldExtractor()
        self.raw_dir = RAW_DIR
        self.stats = {"sources_queried": 0, "items_discovered": 0,
                       "pages_fetched": 0, "interventions_created": 0,
                       "full_texts": 0}

    def run_opencli(self, command: str, timeout: int = 30) -> list[dict]:
        full_cmd = f"opencli {command} -f json"
        result = subprocess.run(full_cmd, shell=True, capture_output=True,
                                 text=True, timeout=timeout)
        if result.returncode != 0:
            return []
        return json.loads(result.stdout) if result.stdout.strip() else []

    def fetch_article_text(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        try:
            import requests
            from bs4 import BeautifulSoup
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            self.stats["full_texts"] += 1
            return text[:10000]
        except Exception:
            return ""

    def extract_metadata(self, item: dict, source: str) -> dict:
        title = item.get("title", item.get("name", item.get("text", "")))
        url = item.get("url", item.get("link", ""))
        text = item.get("text", item.get("snippet", item.get("content", "")))
        author = item.get("author", item.get("by", item.get("user", "")))
        score = item.get("score", item.get("points", 0))
        return {"title": title, "url": url, "text": text,
                "author": author, "score": score, "source": source}

    def collect_source(self, source: str, command: str,
                       limit: int = 50, fetch_texts: bool = False) -> list[dict]:
        results = self.run_opencli(command)
        if not results:
            return []
        if isinstance(results, list):
            results = results[:limit]
        items = []
        for item in results:
            meta = self.extract_metadata(item, source)
            if fetch_texts and meta["url"]:
                full_text = self.fetch_article_text(meta["url"])
                if full_text:
                    meta["text"] = full_text + "\n" + meta["text"]
            items.append(meta)
        return items

    def collect_all(self, sources_config: list, fetch_texts: bool = True) -> list[dict]:
        all_items = []
        for cfg in sources_config:
            try:
                items = self.collect_source(
                    cfg["source"], cfg["command"],
                    cfg.get("limit", 50), fetch_texts
                )
                for item in items:
                    item["intervention_type"] = cfg.get("intervention_type", "unknown")
                    item["problem"] = cfg.get("problem", "")
                all_items.extend(items)
                self.stats["sources_queried"] += 1
                self.stats["items_discovered"] += len(items)
                print(f"  {cfg['source']}: {len(items)} items")
            except Exception as e:
                print(f"  {cfg['source']}: FAILED - {e}")
        return all_items

    def process_into_collector(self, items: list[dict], target: int = 5000):
        init_db()
        session = get_session()
        processed = 0

        try:
            for item in items:
                if processed >= target:
                    break
                url = item.get("url", "")
                title = item.get("title", "")
                text = item.get("text", "")

                if not title or len(title) < 10:
                    continue

                existing = session.query(InterventionRecord).filter_by(
                    intervention_title=title[:200]
                ).first()
                if existing:
                    continue

                content_hash = hashlib.sha256(text.encode()).hexdigest()

                doc = Document(
                    id=str(uuid.uuid4()),
                    url=url or f"opencli://{item.get('source')}/{processed}",
                    title=title[:500],
                    content_hash=content_hash,
                    document_type="html",
                    crawl_status="success",
                    cleaned_text=text[:5000],
                    retrieved_at=datetime.utcnow()
                )
                session.add(doc)
                session.flush()

                fields = self.field_extractor.extract_all(text or title)
                families = fields.get("organization_industry", []) or ["unknown"]

                inv = InterventionRecord(
                    id=str(uuid.uuid4()),
                    source_id=item.get("source", "opencli"),
                    document_id=doc.id,
                    organization_name=fields.get("organization_name"),
                    organization_industry=fields.get("organization_industry", []),
                    organization_employee_count=fields.get("organization_employee_count"),
                    organization_employee_band=fields.get("organization_employee_band"),
                    problem_business_function=fields.get("problem_business_function", []),
                    problem_statement=fields.get("problem_statement", "") or title,
                    problem_categories=[item.get("problem")] if item.get("problem") else [],
                    intervention_title=title[:500],
                    intervention_families=families,
                    intervention_description=(text or title)[:5000],
                    intervention_implementation_cost=fields.get("intervention_implementation_cost"),
                    intervention_implementation_time_value=fields.get("intervention_implementation_time_value"),
                    intervention_implementation_time_unit=fields.get("intervention_implementation_time_unit"),
                    intervention_software=fields.get("software", []),
                    intervention_teams_involved=fields.get("teams_involved", []),
                    result_status=self._detect_status(text or title),
                    has_baseline=fields.get("has_baseline", False),
                    has_post_measurement=fields.get("has_post_measurement", False),
                    has_control_group=fields.get("has_control_group", False),
                    sample_size=fields.get("sample_size"),
                    independently_verified=fields.get("independently_verified", False),
                    vendor_reported=fields.get("vendor_reported", False),
                    extractor="opencli_bridge_v1",
                    extracted_at=datetime.utcnow(),
                )
                session.add(inv)
                session.flush()
                processed += 1

                if fields.get("has_baseline") or fields.get("has_post_measurement"):
                    metric = MetricRecord(
                        id=str(uuid.uuid4()),
                        intervention_id=inv.id,
                        source_id=item.get("source", "opencli"),
                        metric_name="outcome_found",
                        metric_category="qualitative",
                        reported_text=title[:500],
                        value_type="reported"
                    )
                    session.add(metric)

                for flag_name in self._gen_flags(fields, text):
                    session.add(QualityFlag(
                        id=str(uuid.uuid4()),
                        intervention_id=inv.id,
                        flag_name=flag_name
                    ))

                if processed % 50 == 0:
                    session.commit()
                    print(f"  Processed {processed} records...")

            session.commit()
        finally:
            session.close()

        self.stats["interventions_created"] = processed
        return processed

    def _detect_status(self, text: str) -> str:
        tl = text.lower() if text else ""
        if any(kw in tl for kw in ["failed", "abandoned", "cancelled", "unsuccessful"]):
            return "failed"
        if any(kw in tl for kw in ["success", "improved", "exceeded", "achieved"]):
            return "successful"
        if any(kw in tl for kw in ["partial", "mixed", "limited"]):
            return "partial"
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
        return flags

    def export(self):
        from compass_collector.export.formats import ExportEngine
        ExportEngine(str(EXPORTS_DIR)).export_all(["jsonl", "csv"])
