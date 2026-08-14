"""Tests for evidence governance — metadata counts and retrieval isolation (migration 2026-08-14).

Uses an ISOLATED temp-file engine (full model schema) so it never mutates the
shared default fixture database. get_session is patched for the metadata path;
retrieval is tested with an explicit session.
"""
import os
import sqlalchemy
import sqlalchemy.orm
import tempfile
import unittest
from unittest import mock

from compass_collector.database import Base
import compass_collector.models.intervention  # noqa: F401
from compass_collector.models.intervention import InterventionRecord
from compass_collector.analysis.candidate_retrieval import _sql_comparable_candidates

_TMP = tempfile.TemporaryDirectory()
DB_PATH = os.path.join(_TMP.name, "governance.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_Session = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)


def _mk(session, rid, status, verification, families='["Workflow_Automation"]', bf='["operations"]'):
    session.add(InterventionRecord(
        id=rid,
        organization_name="TestOrg " + rid,
        problem_business_function=bf,
        intervention_families=families,
        intervention_title="Test intervention " + rid,
        publication_status=status,
        verification_status=verification,
    ))


class TestGovernanceMetadata(unittest.TestCase):

    def setUp(self):
        s = _Session()
        s.query(InterventionRecord).delete()
        _mk(s, "legacy1", "published", "legacy")
        _mk(s, "legacy2", "published", "legacy")
        _mk(s, "verified1", "published", "claim_verified")
        _mk(s, "staging1", "staging", "claim_verified")
        _mk(s, "quar1", "quarantined", "rejected")
        _mk(s, "rej1", "rejected", "rejected")
        s.commit()
        s.close()

    def test_metadata_governance_counts(self):
        # Patch get_session so _compute_metadata reads from our isolated DB.
        from compass_collector.api import app
        with mock.patch.object(app, "get_session", side_effect=lambda: _Session()):
            meta = app._compute_metadata()
        self.assertEqual(meta["total_intervention_records"], 6)
        self.assertEqual(meta["published_records"], 3)
        self.assertEqual(meta["legacy_published_records"], 2)
        self.assertEqual(meta["verified_published_records"], 1)
        self.assertEqual(meta["staging_records"], 1)
        self.assertEqual(meta["quarantined_records"], 1)
        self.assertEqual(meta["rejected_records"], 1)
        # Backward-compat fields preserved
        self.assertIn("gold", meta)
        self.assertIn("decision_grade", meta)
        self.assertIn("supporting", meta)
        self.assertIn("unique_organizations", meta)


class TestRetrievalIsolation(unittest.TestCase):

    def setUp(self):
        s = _Session()
        s.query(InterventionRecord).delete()
        _mk(s, "legacy1", "published", "legacy")
        _mk(s, "verified1", "published", "claim_verified")
        _mk(s, "staging1", "staging", "claim_verified")
        _mk(s, "quar1", "quarantined", "rejected")
        _mk(s, "rej1", "rejected", "rejected")
        s.commit()
        s.close()

    def _retrieve(self):
        s = _Session()
        try:
            return _sql_comparable_candidates(
                session=s,
                business_function="operations",
                constraint="workflow automation",
                max_candidates=100,
            )
        finally:
            s.close()

    def test_legacy_and_verified_published_retrievable(self):
        ids = {r.id for r in self._retrieve()}
        self.assertIn("legacy1", ids)
        self.assertIn("verified1", ids)

    def test_staging_quarantined_rejected_excluded(self):
        ids = {r.id for r in self._retrieve()}
        self.assertNotIn("staging1", ids)
        self.assertNotIn("quar1", ids)
        self.assertNotIn("rej1", ids)


if __name__ == "__main__":
    unittest.main()
