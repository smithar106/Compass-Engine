import unittest
import uuid
import hashlib
from pathlib import Path
from datetime import datetime

from compass_collector.database import init_db, get_session, engine, Base
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag
from compass_collector.extraction.content import ContentExtractor, InterventionDetector, MetricExtractor


class TestInterventionDetector(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.detector = InterventionDetector()
        self.metrics = MetricExtractor()
        self.session = get_session()

        self.doc = Document(
            id=str(uuid.uuid4()),
            source_registry_id=str(uuid.uuid4()),
            url="https://test.com/study",
            title="Test Study",
            content_hash=hashlib.sha256(b"test").hexdigest(),
            document_type="html",
            crawl_status="success"
        )
        self.session.add(self.doc)
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_detect_successful_ai_case_study(self):
        text = (
            "A large enterprise implemented a generative AI chatbot for customer support. "
            "The AI system with human-in-the-loop review handled 60% of inquiries automatically. "
            "Results: average resolution time reduced by 40%. Customer satisfaction improved. "
            "The project was completed on time and under budget. This was a major success for the organization."
        )
        interventions = self.detector.detect(self.doc, text)
        self.assertGreater(len(interventions), 0)
        inv = interventions[0]
        self.assertIn("generative_ai", inv.intervention_families)
        self.assertIn("human_in_the_loop_ai", inv.intervention_families)
        self.assertEqual(inv.result_status, "successful")

    def test_detect_failed_intervention(self):
        text = (
            "The RPA implementation was abandoned after 8 months. "
            "The project failed due to lack of executive sponsorship and poor documentation. "
            "No measurable improvement was observed. The company reverted to manual processing."
        )
        interventions = self.detector.detect(self.doc, text)
        self.assertGreater(len(interventions), 0)
        self.assertEqual(interventions[0].result_status, "abandoned")

    def test_metric_extraction(self):
        text = (
            "The intervention resulted in $2.5 million in cost savings. "
            "Processing time was reduced by 35%. "
            "Customer satisfaction improved from 72 to 88. "
            "The team saved 12,000 hours annually."
        )
        metrics = self.metrics.extract(self.doc, text, str(uuid.uuid4()))
        self.assertGreater(len(metrics), 0)
        metric_names = [m.metric_name for m in metrics]
        self.assertIn("cost_savings", metric_names)
        self.assertIn("percentage_change", metric_names)
        self.assertIn("customer_satisfaction", metric_names)

    def test_detect_no_intervention(self):
        text = "This is a general article about industry trends with no specific implementation details."
        interventions = self.detector.detect(self.doc, text)
        self.assertEqual(len(interventions), 0)

    def test_quality_flags_generated(self):
        text = (
            "Our vendor partner deployed an industry-first AI solution. "
            "Projected cost savings of 50%. No baseline data available."
        )
        interventions = self.detector.detect(self.doc, text)
        if interventions:
            inv_id = interventions[0].id
            flags = self.session.query(QualityFlag).filter_by(intervention_id=inv_id).all()
            flag_names = [f.flag_name for f in flags]
            self.assertIn("marketing_claim", flag_names)
            self.assertIn("projected_rather_than_observed", flag_names)

    def test_metric_currency_parsing(self):
        text = "$1.5 million in annual savings achieved through automation."
        metrics = self.metrics.extract(self.doc, text, str(uuid.uuid4()))
        cost_metrics = [m for m in metrics if m.metric_name == "cost_savings"]
        self.assertGreater(len(cost_metrics), 0)

    def test_metric_percentage_parsing(self):
        text = "Error rate decreased by 67% after implementing the new system."
        metrics = self.metrics.extract(self.doc, text, str(uuid.uuid4()))
        pct_metrics = [m for m in metrics if m.metric_name == "percentage_change"]
        self.assertGreater(len(pct_metrics), 0)
        self.assertAlmostEqual(pct_metrics[0].percentage_change, 67.0)

    def test_duplicate_detection(self):
        from compass_collector.engine.deduplication import DeduplicationEngine
        dedup = DeduplicationEngine()
        content_a = "This is a case study about AI implementation with significant results."
        content_b = "This is a case study about AI implementation with significant results."
        doc_a = Document(
            id=str(uuid.uuid4()),
            url="https://test.com/a",
            content_hash=hashlib.sha256(content_a.encode()).hexdigest(),
            crawl_status="success"
        )
        doc_b = Document(
            id=str(uuid.uuid4()),
            url="https://test.com/b",
            content_hash=hashlib.sha256(content_b.encode()).hexdigest(),
            crawl_status="success"
        )
        session = get_session()
        try:
            session.add(doc_a)
            session.add(doc_b)
            session.commit()
            rels = dedup.deduplicate_documents()
            self.assertGreater(len(rels), 0)
        finally:
            session.close()

    def test_passage_record_creation(self):
        from compass_collector.models.intervention import PassageRecord
        passage = PassageRecord(
            id=str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            intervention_id=str(uuid.uuid4()),
            document_id=self.doc.id,
            page_number=14,
            section="Results",
            passage_text="Average resolution time decreased by 40%.",
            supports_fields=["outcomes.0.percentage_change"],
            extraction_confidence=0.94
        )
        session = get_session()
        try:
            session.add(passage)
            session.commit()
            fetched = session.query(PassageRecord).filter_by(id=passage.id).first()
            self.assertEqual(fetched.page_number, 14)
            self.assertEqual(fetched.section, "Results")
        finally:
            session.close()

    def test_vendor_reported_flag(self):
        text = "According to TechVendor's annual impact report, their solution delivered a 300% ROI for a leading enterprise client."
        interventions = self.detector.detect(self.doc, text)
        if interventions:
            flags = self.session.query(QualityFlag).filter_by(
                intervention_id=interventions[0].id
            ).all()
            self.assertTrue(any("vendor" in f.flag_name for f in flags))


if __name__ == "__main__":
    unittest.main()
