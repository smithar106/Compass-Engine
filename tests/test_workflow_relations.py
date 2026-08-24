"""Tests for the canonical workflow relations layer (retrieval V1.1).

Covers: relation typing (EXACT / ALIAS / RELATED / PARTIAL_TEXT / UNRELATED),
deterministic scoring, record-tag normalization, and explainability fields.
"""

from __future__ import annotations

import unittest

from compass_collector.analysis.workflow_relations import (
    WorkflowRelation,
    normalize_record_tag,
    resolve_query_workflow,
    score_workflow_relation,
)


class TestWorkflowRelationScoring(unittest.TestCase):

    def test_exact_relation(self):
        r = score_workflow_relation("invoice_processing", "", "invoice_processing")
        self.assertEqual(r["match_type"], WorkflowRelation.EXACT)
        self.assertEqual(r["score"], 1.0)
        self.assertEqual(r["matched_workflows"], ["invoice_processing"])

    def test_alias_relation_invoice_to_ap(self):
        # The core reconciliation: query invoice_processing ↔ record accounts_payable.
        r = score_workflow_relation("invoice_processing", "", "accounts_payable")
        self.assertEqual(r["match_type"], WorkflowRelation.ALIAS)
        self.assertEqual(r["score"], 0.9)
        self.assertIn("accounts_payable", r["matched_workflows"])

    def test_alias_relation_ap_to_invoice(self):
        r = score_workflow_relation("accounts_payable", "", "invoice_processing")
        self.assertEqual(r["match_type"], WorkflowRelation.ALIAS)
        self.assertEqual(r["score"], 0.9)

    def test_related_relation_invoice_to_reporting(self):
        r = score_workflow_relation("invoice_processing", "", "financial_reporting")
        self.assertEqual(r["match_type"], WorkflowRelation.RELATED)
        self.assertEqual(r["score"], 0.55)

    def test_related_relation_onboarding_to_knowledge(self):
        r = score_workflow_relation("onboarding", "", "knowledge_base")
        self.assertEqual(r["match_type"], WorkflowRelation.RELATED)

    def test_unrelated_returns_zero(self):
        r = score_workflow_relation("invoice_processing", "", "warehouse_management")
        self.assertEqual(r["match_type"], WorkflowRelation.UNRELATED)
        self.assertEqual(r["score"], 0.0)

    def test_relationship_strengths_are_distinct(self):
        # ALIAS must score higher than RELATED; neither equals EXACT.
        alias = score_workflow_relation("invoice_processing", "", "accounts_payable")["score"]
        related = score_workflow_relation("invoice_processing", "", "financial_reporting")["score"]
        exact = score_workflow_relation("invoice_processing", "", "invoice_processing")["score"]
        self.assertGreater(alias, related)
        self.assertGreater(exact, alias)
        self.assertLess(related, alias)

    def test_free_text_fallback(self):
        # No canonical tag but matching free text still yields partial credit.
        r = score_workflow_relation("invoice processing", "Invoice Processing Automation", "")
        self.assertGreaterEqual(r["score"], 0.3)
        self.assertEqual(r["match_type"], WorkflowRelation.PARTIAL_TEXT)

    def test_unrelated_free_text(self):
        r = score_workflow_relation("invoice processing", "warehouse robotics deployment", "")
        self.assertEqual(r["match_type"], WorkflowRelation.UNRELATED)
        self.assertEqual(r["score"], 0.0)


class TestRecordTagNormalization(unittest.TestCase):

    def test_known_canonical_passes_through(self):
        self.assertEqual(normalize_record_tag("invoice_processing"), "invoice_processing")

    def test_alias_folds_to_canonical(self):
        # contact_center is NOT a canonical slug → folds to call_routing.
        # accounts_payable IS canonical → stays as-is (relation layer handles
        # the alias reconciliation with invoice_processing).
        self.assertEqual(normalize_record_tag("contact_center"), "call_routing")
        self.assertEqual(normalize_record_tag("customer_onboarding"), "onboarding")
        self.assertEqual(normalize_record_tag("order_to_cash_otc"), "order_processing")
        self.assertEqual(normalize_record_tag("accounts_payable"), "accounts_payable")

    def test_unknown_tag_kept_slugified(self):
        self.assertEqual(normalize_record_tag("some_custom_workflow"), "some_custom_workflow")

    def test_empty(self):
        self.assertEqual(normalize_record_tag(""), "")


class TestQueryWorkflowResolution(unittest.TestCase):

    def test_canonical(self):
        self.assertEqual(resolve_query_workflow("invoice_processing"), "invoice_processing")

    def test_free_text_query_maps_to_canonical(self):
        self.assertEqual(resolve_query_workflow("invoice processing"), "invoice_processing")
        # "accounts payable" is itself a canonical slug; the relation layer
        # reconciles it to invoice_processing records as an ALIAS.
        self.assertEqual(resolve_query_workflow("accounts payable"), "accounts_payable")
        self.assertEqual(resolve_query_workflow("employee onboarding"), "onboarding")

    def test_unknown_query_kept_slugified(self):
        self.assertEqual(resolve_query_workflow("some odd query"), "some_odd_query")


if __name__ == "__main__":
    unittest.main()
