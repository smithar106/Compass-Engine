"""Tests for Recommendation Quality KPIs (quality_router.py)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import sqlalchemy

import compass_collector.models.intervention  # noqa: F401
import compass_collector.models.organization  # noqa: F401
import compass_collector.models.analysis_session  # noqa: F401
import compass_collector.models.outcome  # noqa: F401
from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord, MetricRecord

_TMP = tempfile.TemporaryDirectory()
DB_PATH = os.path.join(_TMP.name, "quality.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_TestSession = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)

os.environ["AGENT_SYNC_TOKEN"] = "sync-secret"


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class TestRecommendationQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        session = _TestSession()
        session.add_all([
            InterventionRecord(
                id="g1", organization_name="Acme Corp", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                result_status="completed", has_baseline=True, sample_size=100,
                intervention_measurement_period_value=6,
                implementation_provenance="passage:1", outcome_provenance="passage:2",
            ),
            InterventionRecord(
                id="s1", organization_name="Beta Inc", problem_business_function=["finance"],
                intervention_components={"workflow": "expense reporting"},
                result_status="completed",
                implementation_richness="rich",
            ),
            InterventionRecord(
                id="b1", organization_name="Delta", problem_business_function=["supply_chain"],
                intervention_components={"workflow": "fleet optimization"},
                result_status="unknown",
            ),
        ])
        session.add_all([
            MetricRecord(id="m-g1", intervention_id="g1", metric_name="cost", percentage_change=-40),
            MetricRecord(id="m-s1", intervention_id="s1", metric_name="cost", percentage_change=-20),
        ])
        session.commit()
        session.close()

    def _call(self):
        from compass_collector.api.quality_router import recommendation_quality

        with patch("compass_collector.api.quality_router.get_session", side_effect=lambda: _TestSession()):
            return recommendation_quality(FakeRequest({"X-Compass-Agent-Key": "sync-secret"}))

    def test_evidence_quality_counts(self):
        result = self._call()
        eq = result["evidence_quality"]
        self.assertEqual(result["library_size"], 3)
        self.assertEqual(eq["gold"], 1)
        self.assertEqual(eq["decision_grade"], 1)
        self.assertEqual(eq["supporting"], 1)
        self.assertEqual(eq["high_quality"], 2)
        self.assertAlmostEqual(eq["high_quality_pct"], 66.7, delta=0.1)

    def test_evidence_depth(self):
        result = self._call()
        ed = result["evidence_depth"]
        self.assertEqual(ed["measured_outcome_metrics"], 2)
        self.assertEqual(ed["records_with_baseline"], 1)
        self.assertEqual(ed["records_with_provenance"], 1)

    def test_diversity(self):
        result = self._call()
        div = result["implementation_diversity"]
        self.assertEqual(div["unique_organizations"], 3)
        self.assertEqual(div["unique_workflows"], 3)

    def test_north_star(self):
        result = self._call()
        self.assertEqual(result["north_star"]["1_500_decision_grade"], 2)

    def test_unauthorized(self):
        from compass_collector.api.quality_router import recommendation_quality

        with patch("compass_collector.api.quality_router.get_session", side_effect=lambda: _TestSession()):
            resp, code = recommendation_quality(FakeRequest({"X-Compass-Agent-Key": "wrong"}))
        self.assertEqual(code, 401)


if __name__ == "__main__":
    unittest.main()
