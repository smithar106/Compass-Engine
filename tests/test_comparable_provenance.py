"""Test that ComparableEvidence provenance (source_url, passage, verification) survives retrieval."""
import os
import sqlalchemy
import sqlalchemy.orm
import tempfile
import unittest

from compass_collector.database import Base
import compass_collector.models.intervention  # noqa: F401
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord, PassageRecord
from compass_collector.analysis.retrieval import ImplementationQuery, find_comparable_implementations
from unittest import mock

_TMP = tempfile.TemporaryDirectory()
DB_PATH = os.path.join(_TMP.name, "provenance.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_Session = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)


class TestComparableProvenance(unittest.TestCase):
    def setUp(self):
        s = _Session()
        s.query(InterventionRecord).delete()
        s.query(Document).delete()
        s.query(PassageRecord).delete()
        doc = Document(
            id="doc-p", url="https://www.gov.uk/case-study/verified",
            title="Verified Case Study", content_hash="abc", cleaned_text="implemented automated triage reducing processing time by 50%.",
        )
        s.add(doc)
        rec = InterventionRecord(
            id="rec-p", document_id="doc-p", organization_name="Test Org",
            problem_business_function=["operations"], intervention_families=["workflow_automation"],
            intervention_title="Automated triage", intervention_description="automated triage implementation",
            problem_statement="automated triage of high volume work",
            publication_status="published", verification_status="claim_verified",
        )
        s.add(rec)
        s.add(PassageRecord(id="pas-p", intervention_id="rec-p", document_id="doc-p",
                            passage_text="implemented automated triage reducing processing time by 50%."))
        s.commit()
        s.close()

    @mock.patch("compass_collector.analysis.retrieval.get_session", side_effect=lambda: _Session())
    def test_provenance_fields_survive_retrieval(self, _m):
        q = ImplementationQuery(workflow="automated triage", business_function="operations")
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        target = next((i for i in items if i.get("id") == "rec-p"), None)
        self.assertIsNotNone(target, "record not found in retrieval")
        self.assertEqual(target.get("source_url"), "https://www.gov.uk/case-study/verified")
        self.assertEqual(target.get("source_title"), "Verified Case Study")
        self.assertEqual(target.get("supporting_passage"), "implemented automated triage reducing processing time by 50%.")
        self.assertEqual(target.get("verification_status"), "claim_verified")

    @mock.patch("compass_collector.analysis.retrieval.get_session", side_effect=lambda: _Session())
    def test_legacy_verification_status_defaults(self, _m):
        s = _Session()
        s.query(InterventionRecord).update({"verification_status": "legacy"})
        s.commit()
        s.close()
        q = ImplementationQuery(workflow="automated triage", business_function="operations")
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        target = next((i for i in items if i.get("id") == "rec-p"), None)
        if target:
            self.assertEqual(target.get("verification_status"), "legacy")


if __name__ == "__main__":
    unittest.main()
