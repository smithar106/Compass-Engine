from compass_collector.engine.source_discovery import SourceDiscoveryEngine
from compass_collector.engine.crawl import CrawlEngine
from compass_collector.extraction.content import ContentExtractor, InterventionDetector, MetricExtractor
from compass_collector.engine.deduplication import DeduplicationEngine
from compass_collector.export.formats import ExportEngine
from compass_collector.database import get_session
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag


class PipelineOrchestrator:

    def __init__(self):
        self.discovery = SourceDiscoveryEngine()
        self.crawler = CrawlEngine()
        self.extractor = ContentExtractor()
        self.detector = InterventionDetector()
        self.metrics = MetricExtractor()
        self.dedup = DeduplicationEngine()
        self.exporter = ExportEngine()

    def discover(self, config_path: str = None):
        if config_path:
            return self.discovery.import_yaml(config_path)
        return self.discovery.list_sources()

    def crawl_all(self, source_id: str = None, limit: int = None):
        sources = self.discovery.list_sources()
        if source_id:
            sources = [s for s in sources if s.id == source_id]

        docs = []
        for i, src in enumerate(sources):
            if limit and i >= limit:
                break
            if src.base_url:
                print(f"Crawling {src.source_domain} ({src.base_url})")
                doc = self.crawler.fetch(src.base_url, src.id, src.rate_limit or 1.0, src.parser_type or "html")
                docs.append(doc)
        return docs

    def process_pending(self):
        session = get_session()
        try:
            pending = session.query(Document).filter(
                Document.crawl_status == "success",
                Document.clean_text_path != ""
            ).all()

            for doc in pending:
                text = self.extractor.extract_text(doc)
                interventions = self.detector.detect(doc, text)
                for inv in interventions:
                    self.metrics.extract(doc, text, inv.id)
                print(f"  Processed: {doc.title[:60] or doc.url[:60]} → {len(interventions)} interventions")

            return len(pending)
        finally:
            session.close()

    def deduplicate(self):
        exact = self.dedup.deduplicate_documents()
        near = self.dedup.detect_near_duplicates()
        same = self.dedup.detect_same_case_study()
        return {"exact": len(exact), "near": len(near), "same_study": len(same)}

    def export(self, formats: list[str] = None):
        return self.exporter.export_all(formats)

    def status(self) -> dict:
        session = get_session()
        try:
            return {
                "total_sources": session.query(Document).count(),
                "crawled": session.query(Document).filter_by(crawl_status="success").count(),
                "failed": session.query(Document).filter_by(crawl_status="failed").count(),
                "intervention_count": session.query(InterventionRecord).count(),
                "metrics": session.query(MetricRecord).count(),
                "quality_flags": session.query(QualityFlag).count(),
            }
        finally:
            session.close()
