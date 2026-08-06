"""Phase 4 tests for workflow canonicalization + inference.

Covers: alias normalization, keyword inference (longest-first determinism),
function mapping, raw preservation, the gap engine's consumption of canonical
workflows (category collapse), and backfill payload provenance.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from compass_collector.organization.workflow_taxonomy import (
    WORKFLOW_NORMALIZATION_VERSION,
    infer_workflow,
    normalize_workflow,
    workflow_function,
)
from compass_collector.organization.backfill import normalize_workflow_record


class TestWorkflowNormalization(unittest.TestCase):
    def test_exact_alias(self):
        nv = normalize_workflow("Invoice Processing")
        self.assertEqual(nv.value, "invoice_processing")
        self.assertEqual(nv.method, "explicit")
        self.assertEqual(nv.confidence, 1.0)

    def test_keyword_inference_longest_first(self):
        # "customer service call handling" must hit call_routing, not
        # the shorter "support" keyword.
        nv = normalize_workflow("customer service call handling and absence reporting")
        self.assertEqual(nv.value, "call_routing")
        self.assertEqual(nv.method, "inferred")
        self.assertGreaterEqual(nv.confidence, 0.6)

    def test_multi_workflow_string_first_match(self):
        nv = normalize_workflow("customer onboarding, supply chain workflows, finance/tax invoice processing")
        self.assertEqual(nv.value, "onboarding")

    def test_unmapped_keeps_slugified_raw(self):
        nv = normalize_workflow("Zz exotic quantum melding")
        self.assertEqual(nv.confidence, 0.3)
        self.assertEqual(nv.value, "zz_exotic_quantum_melding")
        self.assertEqual(nv.raw, "Zz exotic quantum melding")

    def test_function_mapping(self):
        self.assertEqual(workflow_function("invoice_processing"), "finance")
        self.assertEqual(workflow_function("contract_review"), "legal")
        self.assertEqual(workflow_function("warehouse_management"), "operations")
        self.assertIsNone(workflow_function("not_a_workflow"))


class TestWorkflowInference(unittest.TestCase):
    def test_infer_from_title(self):
        nv = infer_workflow("Invoice processing automation reduced processing time by 40%")
        self.assertEqual(nv.value, "invoice_processing")
        self.assertEqual(nv.method, "inferred")
        self.assertEqual(nv.confidence, 0.5)

    def test_infer_returns_uncategorized_for_unknown(self):
        nv = infer_workflow("")
        self.assertEqual(nv.value, "")
        nv2 = infer_workflow("Quantum orb weaving with exotic materials")
        self.assertEqual(nv2.value, "uncategorized")

    def test_infer_contract(self):
        self.assertEqual(infer_workflow("Contract review turnaround improved").value, "contract_review")


class TestBackfillPayload(unittest.TestCase):
    def _rec(self, wf=None, title="", problem=""):
        return NS(
            id="w-1",
            intervention_components={"workflow": wf} if wf else {},
            intervention_title=title,
            problem_statement=problem,
        )

    def test_stored_workflow_payload(self):
        payload = normalize_workflow_record(self._rec(wf="Invoice processing"))
        self.assertEqual(payload["value"], "invoice_processing")
        self.assertEqual(payload["function"], "finance")
        self.assertEqual(payload["version"], WORKFLOW_NORMALIZATION_VERSION)
        self.assertEqual(payload["method"], "explicit")

    def test_inferred_payload(self):
        payload = normalize_workflow_record(
            self._rec(title="Invoice processing automation", problem="AP took 30 days")
        )
        self.assertEqual(payload["value"], "invoice_processing")
        self.assertEqual(payload["method"], "inferred")

    def test_empty_record(self):
        self.assertEqual(normalize_workflow_record(self._rec()), {})


class TestGapEngineConsumption(unittest.TestCase):
    def test_canonical_workflow_drives_category(self):
        from compass_agent.evidence_gap import _record_function, _record_workflow

        rec = NS(
            workflow_normalized={"value": "invoice_processing", "function": "finance",
                                 "confidence": 1.0},
            intervention_components={},
            intervention_title="x", problem_statement="x",
            problem_business_function=[],
        )
        self.assertEqual(_record_workflow(rec), "invoice_processing")
        self.assertEqual(_record_function(rec), "finance")

    def test_fallback_infers_from_text(self):
        from compass_agent.evidence_gap import _record_workflow

        rec = NS(
            workflow_normalized={},
            intervention_components={},
            intervention_title="Invoice processing automation",
            problem_statement="",
            problem_business_function=["finance"],
        )
        self.assertEqual(_record_workflow(rec), "invoice_processing")


if __name__ == "__main__":
    unittest.main()
