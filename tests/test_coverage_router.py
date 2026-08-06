"""Tests for Decision Coverage (coverage_router.py)."""

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
DB_PATH = os.path.join(_TMP.name, "coverage.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_TestSession = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)

os.environ["AGENT_SYNC_TOKEN"] = "sync-secret"


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class TestDecisionCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        session = _TestSession()
        # Finance: 2 gold, 1 silver, 1 bronze
        session.add_all([
            InterventionRecord(
                id="f-g1", organization_name="Acme Corp", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                result_status="completed", has_baseline=True, sample_size=100,
                intervention_measurement_period_value=6,
            ),
            InterventionRecord(
                id="f-g2", organization_name="Beta Inc", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                result_status="completed", has_baseline=True, sample_size=200,
                intervention_measurement_period_value=12,
            ),
            InterventionRecord(
                id="f-s1", organization_name="Gamma LLC", problem_business_function=["finance"],
                intervention_components={"workflow": "expense reporting"},
                result_status="completed",
                implementation_richness="rich",
            ),
            InterventionRecord(
                id="f-b1", organization_name="Delta", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                result_status="unknown",
            ),
            # Supply chain: 1 bronze only
            InterventionRecord(
                id="s-b1", organization_name="Epsilon", problem_business_function=["supply_chain"],
                intervention_components={"workflow": "fleet optimization"},
                result_status="unknown",
            ),
        ])
        session.add_all([
            MetricRecord(id="m-g1", intervention_id="f-g1", metric_name="cost", percentage_change=-40),
            MetricRecord(id="m-g2", intervention_id="f-g2", metric_name="cycle_time", percentage_change=-30),
            MetricRecord(id="m-s1", intervention_id="f-s1", metric_name="cost", percentage_change=-20),
        ])
        session.commit()
        session.close()

    def _call(self):
        from compass_collector.api.coverage_router import decision_coverage

        with patch("compass_collector.api.coverage_router.get_session", side_effect=lambda: _TestSession()):
            return decision_coverage(FakeRequest({"X-Compass-Agent-Key": "sync-secret"}))

    def test_coverage_counts_high_quality_by_function(self):
        result = self._call()
        finance = next(r for r in result["by_business_function"] if r["key"] == "finance")
        supply = next(r for r in result["by_business_function"] if r["key"] == "supply_chain")
        self.assertEqual(finance["total"], 4)
        self.assertEqual(finance["gold"], 2)
        self.assertEqual(finance["decision_grade"], 1)
        self.assertEqual(finance["high_quality"], 3)
        self.assertEqual(supply["high_quality"], 0)
        self.assertEqual(supply["coverage"], "limited")

    def test_coverage_by_workflow(self):
        result = self._call()
        invoice = next(r for r in result["by_workflow"] if r["key"] == "invoice processing")
        fleet = next(r for r in result["by_workflow"] if r["key"] == "fleet optimization")
        self.assertEqual(invoice["high_quality"], 2)
        self.assertIn(invoice["coverage"], ("good", "excellent"))
        self.assertEqual(fleet["high_quality"], 0)
        self.assertEqual(fleet["coverage"], "limited")

    def test_unauthorized(self):
        from compass_collector.api.coverage_router import decision_coverage

        with patch("compass_collector.api.coverage_router.get_session", side_effect=lambda: _TestSession()):
            resp, code = decision_coverage(FakeRequest({"X-Compass-Agent-Key": "wrong"}))
        self.assertEqual(code, 401)


if __name__ == "__main__":
    unittest.main()
