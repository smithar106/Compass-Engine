"""Tests for retrieval integration — canonical workflow threading + explainability.

Verifies that ``compute_similarity`` reads ``workflow_normalized.value`` and
surfaces the workflow match type + matched slugs in the breakdown, and that
the taxonomy relations layer reconciles query/record vocabulary.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from compass_collector.analysis.retrieval import (
    ImplementationQuery,
    compute_similarity,
    _get_canonical_workflow,
)


def _record(**kwargs):
    base = dict(
        id="r1",
        source_id="s1",
        organization_name="Acme",
        organization_industry=None,
        organization_employee_count=None,
        problem_statement="Manual invoice processing is slow",
        problem_baseline_description="",
        intervention_title="Invoice automation",
        intervention_description="",
        intervention_components=None,
        intervention_families=["workflow_automation"],
        workflow_normalized={"value": "accounts_payable"},
    )
    base.update(kwargs)
    return NS(**base)


class TestCanonicalWorkflowExtraction(unittest.TestCase):

    def test_reads_value_from_dict(self):
        rec = _record()
        self.assertEqual(_get_canonical_workflow(rec), "accounts_payable")

    def test_reads_value_from_json_string(self):
        rec = _record(workflow_normalized='{"value": "invoice_processing"}')
        self.assertEqual(_get_canonical_workflow(rec), "invoice_processing")

    def test_empty_when_missing(self):
        rec = _record(workflow_normalized=None)
        self.assertEqual(_get_canonical_workflow(rec), "")


class TestComputeSimilarityThreadsCanonical(unittest.TestCase):

    def test_invoice_query_reconciles_with_ap_record(self):
        query = ImplementationQuery(workflow="invoice_processing", business_function="finance")
        rec = _record()  # workflow_normalized.value = accounts_payable
        sim = compute_similarity(query, rec, [])
        wf = sim["components"]["workflow"]
        # ALIAS relation (invoice_processing ↔ accounts_payable) → raw 0.9.
        self.assertEqual(wf["match_type"], "alias")
        self.assertEqual(wf["raw"], 0.9)
        self.assertIn("accounts_payable", wf["matched_workflows"])

    def test_exact_match_reports_exact(self):
        query = ImplementationQuery(workflow="invoice_processing", business_function="finance")
        rec = _record(workflow_normalized={"value": "invoice_processing"})
        sim = compute_similarity(query, rec, [])
        wf = sim["components"]["workflow"]
        self.assertEqual(wf["match_type"], "exact")
        self.assertEqual(wf["raw"], 1.0)

    def test_legacy_free_text_still_works(self):
        # Record with no canonical tag: falls back to free-text overlap.
        query = ImplementationQuery(workflow="invoice_processing", business_function="finance")
        rec = _record(workflow_normalized=None, intervention_components={"workflow": "Invoice Processing"})
        sim = compute_similarity(query, rec, [])
        wf = sim["components"]["workflow"]
        self.assertEqual(wf["match_type"], "partial_text")
        self.assertGreaterEqual(wf["raw"], 0.5)

    def test_unrelated_workflow_zero(self):
        query = ImplementationQuery(workflow="invoice_processing", business_function="finance")
        rec = _record(workflow_normalized={"value": "warehouse_management"})
        sim = compute_similarity(query, rec, [])
        self.assertEqual(sim["components"]["workflow"]["match_type"], "unrelated")
        self.assertEqual(sim["components"]["workflow"]["raw"], 0.0)


if __name__ == "__main__":
    unittest.main()
