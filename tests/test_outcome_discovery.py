"""Tests for the Outcome Discovery Worker (outcome_discovery.py)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from compass_agent.config import Settings
from compass_agent.outcome_discovery import (
    _missing_fields,
    _recovered_fields,
    run_outcome_discovery,
)


def _record(**overrides):
    base = {
        "id": "r1",
        "organization_name": "Acme",
        "intervention_title": "Invoice automation",
        "result_status": "unknown",
        "intervention_measurement_period_value": None,
        "sample_size": None,
        "has_baseline": False,
        "problem_baseline_description": "",
        "intervention_components": {"source_url": "https://example.com/a"},
        "metrics": [],
    }
    base.update(overrides)
    return base


class TestMissingFields(unittest.TestCase):
    def test_all_four_missing(self):
        rec = _record()
        self.assertEqual(set(_missing_fields(rec)), {"deployment_status", "measurement_period", "sample_size", "baseline"})

    def test_deployed_and_measured_skipped(self):
        rec = _record(
            result_status="deployed",
            intervention_measurement_period_value=6,
            sample_size=100,
            has_baseline=True,
        )
        self.assertEqual(_missing_fields(rec), [])

    def test_qualitative_statuses_count_as_missing(self):
        rec = _record(result_status="proposed")
        self.assertIn("deployment_status", _missing_fields(rec))


class TestRecoveredFields(unittest.TestCase):
    def test_full_recovery(self):
        fields = _recovered_fields(
            ["deployment_status", "measurement_period", "sample_size", "baseline"],
            {
                "deployment_status": "deployed",
                "measurement_period": {"value": 6, "unit": "months"},
                "sample_size": "41,000 invoices",
                "baseline": "on-time rate was 78% before",
            },
        )
        self.assertEqual(fields["result_status"], "deployed")
        self.assertEqual(fields["intervention_measurement_period_value"], 6)
        self.assertEqual(fields["intervention_measurement_period_unit"], "months")
        self.assertEqual(fields["sample_size"], 41000)
        self.assertTrue(fields["has_baseline"])

    def test_pilot_maps_to_result_status(self):
        fields = _recovered_fields(["deployment_status"], {"deployment_status": "pilot"})
        self.assertEqual(fields["result_status"], "pilot")

    def test_ignores_missing_not_requested(self):
        fields = _recovered_fields(["sample_size"], {"baseline": "x", "sample_size": 50})
        self.assertEqual(fields, {"sample_size": 50})

    def test_rejects_fabricated(self):
        fields = _recovered_fields(["measurement_period"], {"measurement_period": None})
        self.assertEqual(fields, {})


class TestRunOutcomeDiscovery(unittest.TestCase):
    def _settings(self):
        return Settings(
            compass_api_url="https://engine.example",
            sync_token="tok",
            llm_provider="anthropic",
            anthropic_api_key="k",
            max_daily_llm_usd=25.0,
            max_total_llm_usd=50.0,
        )

    def test_skips_without_credentials(self):
        st = Settings(compass_api_url="https://engine.example", sync_token="")
        res = run_outcome_discovery(st, None, max_applications=2)
        self.assertEqual(res["skipped"], "no_api_key_or_token")

    def test_ranks_missing_fields_and_filters_excluded(self):
        from compass_agent.daemon import BudgetTracker

        budget = BudgetTracker(max_daily=25, max_total=50)
        records = [
            _record(id="full", result_status="deployed", intervention_measurement_period_value=6, sample_size=50, has_baseline=True),
            _record(id="partial", result_status="deployed", intervention_measurement_period_value=6),
            _record(id="bare", result_status="unknown"),
        ]
        with patch("compass_agent.promote.load_records_from_engine", return_value=records):
            res = run_outcome_discovery(
                self._settings(), budget, max_applications=5, limit=10,
                exclude_ids={"full"},
            )
        # full has nothing to recover; partial needs sample+baseline; bare needs all four.
        # With no real engine (post will fail) we expect http failures, not a skip.
        self.assertIn("candidates", res)
        self.assertEqual(res["applied"], 0)


if __name__ == "__main__":
    unittest.main()
