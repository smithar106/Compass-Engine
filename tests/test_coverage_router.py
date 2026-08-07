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


class TestEvidenceGapsEndpoint(unittest.TestCase):
    """Phase 5: /api/evidence/gaps is dual-mode — agent key → full report,
    public read → UI-shaped payload (hunt directives stripped)."""

    @classmethod
    def setUpClass(cls):
        session = _TestSession()
        # One weak category (legal/contract review, no decision-grade) so the
        # gap engine produces a ranked shopping list.
        session.add_all([
            InterventionRecord(
                id="g-legal-1", organization_name="LegalCo", problem_business_function=["legal"],
                intervention_components={"workflow": "contract review"},
                result_status="unknown",
            ),
            InterventionRecord(
                id="g-legal-2", organization_name="Firm B", problem_business_function=["legal"],
                intervention_components={"workflow": "contract review"},
                result_status="unknown",
            ),
            InterventionRecord(
                id="g-fin-1", organization_name="Acme Corp", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                result_status="completed", has_baseline=True, sample_size=100,
                intervention_measurement_period_value=6,
            ),
        ])
        session.commit()
        session.close()

    def _call(self, headers=None):
        from compass_collector.api.coverage_router import evidence_gaps

        with patch("compass_collector.api.coverage_router.get_session", side_effect=lambda: _TestSession()):
            return evidence_gaps(FakeRequest(headers or {}))

    def test_public_report_is_ui_shaped(self):
        """No agent key → 200 (not 401) with the KPI/dimension/shopping-list shape."""
        result = self._call()
        self.assertNotIsInstance(result, tuple)  # not a (payload, code) rejection
        self.assertIn("decision_coverage_by_function", result)
        self.assertIn("dimension_coverage", result)
        self.assertIn("shopping_list", result)
        self.assertIn("total_records", result)
        self.assertGreaterEqual(result["total_records"], 3)
        self.assertIn("legal", result["decision_coverage_by_function"])
        self.assertIn("finance", result["decision_coverage_by_function"])

    def test_public_report_strips_hunt_directives(self):
        """UI-shaped needs must not leak search_terms / library priority."""
        result = self._call()
        for bucket in ("needs", "shopping_list"):
            for need in result[bucket]:
                self.assertNotIn("search_terms", need)
                self.assertNotIn("source_library_priority", need)
                self.assertNotIn("vendor_diversity_target", need)
                self.assertNotIn("data_limited_fields", need)
                sl = need.get("shopping_list")
                if isinstance(sl, dict):
                    self.assertNotIn("search_terms", sl)
                    self.assertNotIn("source_library_priority", sl)

    def test_agent_key_gets_full_report(self):
        """With a valid agent key the hunt directives are present."""
        result = self._call({"X-Compass-Agent-Key": "sync-secret"})
        self.assertNotIsInstance(result, tuple)
        needs = result.get("needs") or []
        self.assertTrue(needs)
        found = next((n for n in needs if (n.get("shopping_list") or {}).get("search_terms")), None)
        self.assertIsNotNone(found, "agent report should include search_terms")
        self.assertTrue(found["shopping_list"]["search_terms"])
        self.assertTrue(found["shopping_list"]["source_library_priority"])

    def test_wrong_key_gets_public_report(self):
        """An invalid key degrades to the public UI-shaped report (never 401s
        the product read path)."""
        result = self._call({"X-Compass-Agent-Key": "wrong"})
        self.assertNotIsInstance(result, tuple)
        needs = result.get("needs") or []
        self.assertTrue(needs)
        self.assertNotIn("search_terms", needs[0])


if __name__ == "__main__":
    unittest.main()
