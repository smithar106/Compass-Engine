"""Tests for evidence comparability + outcome attribution (Phase 2).

Verifies the two dimensions stay independent and the fail-closed rule holds:
only direct_implementation + explicit attribution may support a direct-outcome
claim. unassessed/indirect/not_relevant and uncertain/none all fail closed.
"""

from __future__ import annotations

import unittest

import compass_collector.models.intervention  # noqa: F401 — registers table for conftest migration
from compass_collector.analysis.evidence_comparability import (
    Comparability,
    OutcomeAttribution,
    attribution_limitation,
    parse_attribution,
    parse_comparability,
    supports_direct_outcome_claim,
)


class TestParsing(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(parse_comparability("direct_implementation"), Comparability.DIRECT_IMPLEMENTATION)
        self.assertEqual(parse_comparability("INDIRECT_CONTEXTUAL"), Comparability.INDIRECT_CONTEXTUAL)
        self.assertEqual(parse_attribution("explicit"), OutcomeAttribution.EXPLICIT)

    def test_unknown_or_empty_defaults_to_unassessed(self):
        self.assertEqual(parse_comparability(""), Comparability.UNASSESSED)
        self.assertEqual(parse_comparability(None), Comparability.UNASSESSED)
        self.assertEqual(parse_comparability("made_up"), Comparability.UNASSESSED)
        self.assertEqual(parse_attribution(""), OutcomeAttribution.UNASSESSED)
        self.assertEqual(parse_attribution(None), OutcomeAttribution.UNASSESSED)


class TestFailClosedGate(unittest.TestCase):
    def test_direct_plus_explicit_supports(self):
        self.assertTrue(
            supports_direct_outcome_claim("direct_implementation", "explicit")
        )

    def test_direct_but_uncertain_attribution_fails_closed(self):
        self.assertFalse(supports_direct_outcome_claim("direct_implementation", "uncertain"))
        self.assertFalse(supports_direct_outcome_claim("direct_implementation", "none"))
        self.assertFalse(supports_direct_outcome_claim("direct_implementation", "unassessed"))

    def test_unassessed_comparability_fails_closed(self):
        self.assertFalse(supports_direct_outcome_claim("unassessed", "explicit"))
        self.assertFalse(supports_direct_outcome_claim("", "explicit"))

    def test_indirect_and_not_relevant_fail_closed(self):
        self.assertFalse(supports_direct_outcome_claim("indirect_contextual", "explicit"))
        self.assertFalse(supports_direct_outcome_claim("not_relevant", "explicit"))

    def test_source_verification_does_not_imply_comparability(self):
        # A claim_verified source with unassessed comparability must fail closed.
        # (The gate takes comparability, not verification — so this is inherent,
        #  but assert the negative explicitly.)
        self.assertFalse(supports_direct_outcome_claim("unassessed", "unassessed"))


class TestAttributionLimitation(unittest.TestCase):
    def test_limitations_are_stated(self):
        self.assertIn("not yet reviewed", attribution_limitation("unassessed", "unassessed"))
        self.assertIn("Not relevant", attribution_limitation("not_relevant", "none"))
        self.assertIn("Indirect context", attribution_limitation("indirect_contextual", "none"))
        self.assertIn("does not establish", attribution_limitation("direct_implementation", "uncertain"))

    def test_no_limitation_when_fully_supported(self):
        self.assertEqual(attribution_limitation("direct_implementation", "explicit"), "")


class TestVerifiedEndpoint(unittest.TestCase):
    def test_endpoint_returns_records_and_separates_dimensions(self):
        from fastapi.testclient import TestClient
        from compass_collector.api.app import app

        c = TestClient(app)
        r = c.get("/api/evidence/verified?workflow=invoice_processing")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["available"])
        self.assertEqual(d["summary"]["total"], 7)
        # Phase-1 audit classifications preserved.
        self.assertEqual(d["summary"]["direct_implementation"], 0)
        self.assertEqual(d["summary"]["indirect_contextual"], 5)
        self.assertEqual(d["summary"]["not_relevant"], 2)
        self.assertEqual(d["summary"]["supports_direct_outcome"], 0)
        for rec in d["records"]:
            # source dimension present and independent
            self.assertEqual(rec["verification_status"], "claim_verified")
            self.assertIn(rec["comparability"], {"unassessed", "direct_implementation", "indirect_contextual", "not_relevant"})
            self.assertIn(rec["outcome_attribution"], {"unassessed", "explicit", "uncertain", "none"})
            self.assertFalse(rec["supports_direct_outcome"])
            self.assertTrue(rec["attribution_limitation"])

    def test_unknown_workflow_reports_unavailable(self):
        from fastapi.testclient import TestClient
        from compass_collector.api.app import app
        c = TestClient(app)
        d = c.get("/api/evidence/verified?workflow=nonexistent").json()
        self.assertFalse(d["available"])
        self.assertEqual(d["records"], [])


if __name__ == "__main__":
    unittest.main()
