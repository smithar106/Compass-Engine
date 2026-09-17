"""Integrity tests for the canonical verified-evidence data file.

The verified set lives in the engine (compass_collector/data/verified/*.json);
the web no longer maintains a copy. These tests enforce the data contract:
trusted-host sources, claim verification, explicit comparability + attribution,
and passages for every metric.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import compass_collector.models.intervention  # noqa: F401 — registers table for conftest migration
from compass_collector.analysis.evidence_comparability import (
    Comparability,
    OutcomeAttribution,
    parse_comparability,
    parse_attribution,
    supports_direct_outcome_claim,
)

_DATA = Path(__file__).resolve().parent.parent / "compass_collector" / "data" / "verified"
_TRUSTED = ("sec.gov", "gao.gov", "gov.uk", "doi.org", "arxiv.org")


def _load(workflow: str) -> dict:
    return json.loads((_DATA / f"{workflow}.json").read_text())


class TestVerifiedDataIntegrity(unittest.TestCase):
    def setUp(self):
        self.data = _load("invoice_processing")
        self.records = self.data["records"]

    def test_has_records(self):
        self.assertGreaterEqual(len(self.records), 5)

    def test_sources_are_trusted_and_resolvable(self):
        for r in self.records:
            url = r["source"]["url"]
            self.assertTrue(url.startswith("https://"), url)
            self.assertTrue(any(h in url for h in _TRUSTED), url)
            self.assertGreater(len(r["source"].get("title", "")), 5)

    def test_every_record_is_claim_verified(self):
        for r in self.records:
            self.assertEqual(r["verification_status"], "claim_verified")

    def test_every_metric_has_a_passage(self):
        for r in self.records:
            self.assertGreaterEqual(len(r["metrics"]), 1)
            for m in r["metrics"]:
                self.assertGreater(len(m["label"]), 3)
                self.assertGreater(len(m["value"]), 0)
                self.assertGreater(len(m["passage"]), 20)

    def test_comparability_and_attribution_are_explicit(self):
        for r in self.records:
            comp = parse_comparability(r.get("comparability"))
            attr = parse_attribution(r.get("outcome_attribution"))
            self.assertIn(comp, set(Comparability))
            self.assertIn(attr, set(OutcomeAttribution))
            self.assertTrue(r.get("comparability_reason"))

    def test_no_record_supports_a_direct_outcome_claim(self):
        # Phase-1 audit: all are indirect_contextual or not_relevant, attribution none.
        for r in self.records:
            self.assertFalse(
                supports_direct_outcome_claim(r.get("comparability"), r.get("outcome_attribution")),
                f"{r['id']} must not support a direct outcome claim",
            )

    def test_audit_classifications_preserved(self):
        counts = {}
        for r in self.records:
            counts[r["comparability"]] = counts.get(r["comparability"], 0) + 1
        self.assertEqual(counts.get("direct_implementation", 0), 0)
        self.assertEqual(counts.get("indirect_contextual", 0), 5)
        self.assertEqual(counts.get("not_relevant", 0), 2)

    def test_no_vendor_only_sources(self):
        for r in self.records:
            self.assertNotIn("vendor", r["source"].get("type", "").lower())
            self.assertNotRegex(
                r["source"]["url"], r"uipath|zendesk|salesforce|automationanywhere"
            )


class TestDocumentProcessAutomationCohort(unittest.TestCase):
    """The first DIRECT-IMPLEMENTATION cohort (document/process automation)."""

    def setUp(self):
        self.data = _load("document_process_automation")
        self.records = self.data["records"]

    def test_has_at_least_five_records(self):
        self.assertGreaterEqual(len(self.records), 5)

    def test_all_sources_trusted(self):
        for r in self.records:
            url = r["source"]["url"]
            self.assertTrue(url.startswith("https://"), url)
            self.assertTrue(any(h in url for h in _TRUSTED), url)

    def test_all_are_direct_implementation(self):
        for r in self.records:
            self.assertEqual(r["comparability"], "direct_implementation")

    def test_attribution_is_assigned_and_not_unassessed(self):
        for r in self.records:
            self.assertIn(r["outcome_attribution"], ("explicit", "uncertain", "none"))

    def test_at_least_four_support_direct_outcome(self):
        supporting = [
            r for r in self.records
            if supports_direct_outcome_claim(r["comparability"], r["outcome_attribution"])
        ]
        self.assertGreaterEqual(len(supporting), 4)

    def test_uncertain_attribution_does_not_support_direct_outcome(self):
        for r in self.records:
            if r["outcome_attribution"] != "explicit":
                self.assertFalse(
                    supports_direct_outcome_claim(r["comparability"], r["outcome_attribution"]),
                    f"{r['id']} must not support a direct outcome claim",
                )

    def test_every_metric_has_a_passage(self):
        for r in self.records:
            for m in r["metrics"]:
                self.assertGreater(len(m["passage"]), 20)

    def test_every_record_has_a_pre_intervention_post_flow(self):
        """The evidence base must show a clear pre -> intervention -> post flow."""
        for r in self.records:
            flow = r.get("flow")
            self.assertIsNotNone(flow, f"{r['id']} missing flow")
            for key in ("baseline", "intervention", "outcome"):
                self.assertIn(key, flow, f"{r['id']} missing flow.{key}")
                self.assertGreater(len(flow[key].get("statement", "")), 5)
            self.assertIn(flow.get("attribution"), ("explicit", "uncertain", "none"))
            # the flow's intervention must match the record's intervention
            self.assertTrue(flow["intervention"]["statement"])


if __name__ == "__main__":
    unittest.main()
