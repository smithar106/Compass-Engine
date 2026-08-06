"""Phase 4/5 tests — discovery inversion + demand telemetry.

Covers: DuckDuckGoSearch.build_queries honoring campaign search terms,
Campaign carrying shopping-list directives, the evidence-ops planner
preferring the gap-engine need over v1 gaps, and demand telemetry
recording/export (isolated to a temp DATA_DIR).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace as NS

from compass_agent.campaign import Campaign
from compass_agent.discovery import DuckDuckGoSearch, build_queries


class TestCampaignDirectives(unittest.TestCase):
    def test_defaults_empty(self):
        c = Campaign(workflow="invoice_processing", business_function="finance")
        self.assertEqual(c.search_terms, [])
        self.assertEqual(c.library_priority, [])

    def test_carries_shopping_list(self):
        c = Campaign(workflow="invoice_processing", business_function="finance",
                     search_terms=["invoice processing finance implementation"],
                     library_priority=["servicenow"])
        self.assertEqual(len(c.search_terms), 1)
        self.assertEqual(c.library_priority[0], "servicenow")


class TestDuckDuckGoTargeted(unittest.TestCase):
    def test_search_terms_override_generic_queries(self):
        backend = DuckDuckGoSearch()
        campaign = Campaign(
            workflow="invoice_processing", business_function="finance",
            search_terms=["invoice processing finance implementation",
                          "invoice processing automation quantified results"],
        )
        queries = backend.build_queries(campaign)
        self.assertEqual(queries, campaign.search_terms)

    def test_no_terms_falls_back_to_generic(self):
        backend = DuckDuckGoSearch()
        campaign = Campaign(workflow="invoice_processing", business_function="finance")
        queries = backend.build_queries(campaign)
        self.assertGreater(len(queries), 1)
        self.assertTrue(any("invoice processing" in q for q in queries))


class TestEvidenceOpsPlanning(unittest.TestCase):
    def test_gap_engine_need_maps_to_planner_input(self):
        """The v2 need must map onto v1 GapCategory for the planner."""
        from compass_agent import evidence_ops as eo
        from compass_agent.evidence_gap import EvidenceNeed

        need = EvidenceNeed(
            workflow="contract_review", business_function="legal",
            total_records=1, gold=0, decision_grade=0, supporting=1,
            field_coverage={}, missing_fields=["rollout_strategy"],
            gap_score=0.8, demand=0.6, expected_impact=0.48,
            estimated_records_needed=7,
        )
        gaps = eo._needs_to_gaps(need)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].workflow, "contract_review")
        self.assertEqual(gaps[0].business_function, "legal")
        self.assertEqual(gaps[0].expected_impact, 0.48)
        self.assertEqual(gaps[0].estimated_records_needed, 7)
        self.assertEqual(gaps[0].missing_fields, ["rollout_strategy"])


class TestDemandTelemetry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["COMPASS_DATA_DIR_OVERRIDE"] = self._tmp

    def tearDown(self):
        os.environ.pop("COMPASS_DATA_DIR_OVERRIDE", None)

    def _import_module(self):
        import importlib

        import compass_collector.api.demand_telemetry as dt

        dt.DEMAND_FILE = dt.Path(self._tmp) / "telemetry" / "demand.json"
        return dt

    def test_record_and_export(self):
        dt = self._import_module()
        slug = dt.record_demand_from_text("Invoice processing automation for accounts payable")
        self.assertEqual(slug, "invoice_processing")
        dt.record_demand_from_text("Invoice processing at scale")
        dt.record_demand_from_text("Contract review turnaround")
        demand = dt.load_demand_for_engine()
        self.assertEqual(demand["invoice_processing"], 1.0)  # top = normalized to 1
        self.assertEqual(demand["contract_review"], 0.5)
        summary = dt.demand_summary()
        self.assertEqual(summary["distinct_workflows"], 2)

    def test_ignores_no_signal_text(self):
        dt = self._import_module()
        self.assertIsNone(dt.record_demand_from_text(""))
        self.assertIsNone(dt.record_demand_from_text("Quantum orb weaving with exotic materials"))
        self.assertEqual(dt.load_demand_for_engine(), {})


if __name__ == "__main__":
    unittest.main()
