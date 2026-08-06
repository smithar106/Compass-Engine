"""Tests for Gold Record Pages rendering (pages_router.py)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import sqlalchemy

import compass_collector.models.intervention  # noqa: F401
from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord

_TMP = tempfile.TemporaryDirectory()
DB_PATH = os.path.join(_TMP.name, "pages.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_TestSession = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)

os.environ["AGENT_SYNC_TOKEN"] = "sync-secret"


class FakeReq:
    def __init__(self, ok):
        self.headers = {"X-Compass-Agent-Key": "sync-secret" if ok else "wrong"}


class TestGoldPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = _TestSession()
        s.add(InterventionRecord(
            id="gold-1", organization_name="Acme", organization_industry=["logistics"],
            organization_employee_count=500, organization_anonymized=False,
            problem_statement="Late deliveries",
            problem_business_function=["supply_chain"],
            intervention_title="Dynamic routing",
            intervention_description="Routing rewrite",
            intervention_components={
                "workflow": "last-mile",
                "intervention_category": "optimization",
                "evidence_tier": "Gold",
                "source_generation": "agent_discovered",
                "source_url": "https://example.com/cs",
            },
            intervention_vendors=["VendorX"],
            rollout_strategy="phased",
            governance_model="steerco",
            lessons_learned=["Start small"],
            success_factors=["Executive sponsor"],
            risks=["cost"],
            result_status="completed",
            sample_size=50, has_baseline=True,
            implementation_richness="gold",
        ))
        s.add(MetricRecord(
            id="m1", intervention_id="gold-1", metric_name="on_time_rate",
            percentage_change=18, reported_text="on-time rose 18%",
        ))
        s.add(PassageRecord(
            id="p1", intervention_id="gold-1", section="Results", page_number=4,
            passage_text="on-time contract rose from 78% to 96%", extraction_confidence=0.95,
        ))
        s.commit()
        s.close()

    def _call(self, req):
        from compass_collector.api.pages_router import gold_page
        with patch("compass_collector.api.pages_router.get_session", side_effect=lambda: _TestSession()):
            return gold_page("gold-1", req)

    def test_renders_structured_asset(self):
        result = self._call(FakeReq(True))
        imp = result["implementation"]
        self.assertTrue(imp["is_gold_asset"])
        self.assertEqual(imp["organization"]["name"], "Acme")
        self.assertEqual(imp["intervention"]["category"], "optimization")
        self.assertEqual(imp["deployment"]["result_status"], "completed")
        self.assertEqual(imp["source_url"], "https://example.com/cs")
        self.assertEqual(len(imp["risk_and_learning"]["lessons_learned"]), 1)

    def test_outcomes_include_metrics(self):
        result = self._call(FakeReq(True))
        outs = result["implementation"]["outcomes"]["metrics"]
        self.assertEqual(outs[0]["name"], "on_time_rate")
        self.assertEqual(result["implementation"]["evidence_quality"]["passage_count"], 1)

    def test_unauthorized(self):
        from compass_collector.api.pages_router import gold_page
        with patch("compass_collector.api.pages_router.get_session", side_effect=lambda: _TestSession()):
            try:
                gold_page("gold-1", FakeReq(False))
                self.fail("expected 401")
            except Exception as e:  # HTTPException
                self.assertEqual(e.status_code, 401)

    def test_missing(self):
        from compass_collector.api.pages_router import gold_page
        with patch("compass_collector.api.pages_router.get_session", side_effect=lambda: _TestSession()):
            try:
                gold_page("nope", FakeReq(True))
                self.fail("expected 404")
            except Exception as e:
                self.assertEqual(e.status_code, 404)


if __name__ == "__main__":
    unittest.main()