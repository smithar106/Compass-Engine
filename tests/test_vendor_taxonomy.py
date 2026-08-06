"""Phase 4 tests for the canonical vendor/technology knowledge layer.

Covers: vendor alias normalization (legal suffixes, trademarks, parentheticals,
equivalent labels), fuzzy keyword matching, technology product-family mapping,
prefix matching for product-level strings, provenance retention, unmapped long
tail preservation, and determinism.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from compass_collector.organization.vendor_taxonomy import (
    normalize_technology,
    normalize_vendor,
    technology_family,
    technology_label,
    vendor_label,
)
from compass_collector.organization.backfill import normalize_vendors_software


class TestVendorNormalization(unittest.TestCase):
    def test_aws_aliases_all_normalize_to_aws(self):
        for raw in ("AWS", "Amazon Web Services", "Amazon Web Services (AWS)",
                    "Amazon Web Services, Inc.", "aws"):
            nv = normalize_vendor(raw)
            self.assertEqual(nv.value, "aws", raw)
            self.assertGreaterEqual(nv.confidence, 0.7, raw)

    def test_google_aliases(self):
        for raw in ("Google Cloud", "Google Cloud Platform", "GCP", "Google"):
            self.assertEqual(normalize_vendor(raw).value, "google_cloud", raw)

    def test_consulting_aliases(self):
        self.assertEqual(normalize_vendor("PwC").value, "pwc")
        self.assertEqual(normalize_vendor("PWC").value, "pwc")
        self.assertEqual(normalize_vendor("PricewaterhouseCoopers").value, "pwc")
        self.assertEqual(normalize_vendor("Bain & Company").value, "bain")
        self.assertEqual(normalize_vendor("McKinsey & Company").value, "mckinsey")

    def test_trademarks_and_parentheticals_stripped(self):
        self.assertEqual(normalize_vendor("Immix®").value, "immix")
        self.assertEqual(normalize_vendor("SARA™").value, "sara")
        self.assertEqual(normalize_vendor("Slack (Salesforce)").value, "slack")
        self.assertEqual(normalize_vendor("Robotic Assistance Devices, Inc. (RAD)").value, "rad")

    def test_fuzzy_keyword_matching(self):
        self.assertEqual(normalize_vendor("Oracle Consulting").value, "oracle")
        self.assertEqual(normalize_vendor("IBM Watson").value, "ibm")
        self.assertEqual(normalize_vendor("Amazon EC2").value, "aws")

    def test_unmapped_vendor_keeps_raw_low_confidence(self):
        nv = normalize_vendor("Apply Digital")
        self.assertEqual(nv.confidence, 0.3)
        self.assertEqual(nv.raw, "Apply Digital")
        self.assertIsNotNone(nv.value)  # never dropped

    def test_vendor_label(self):
        self.assertEqual(vendor_label("aws"), "Amazon Web Services")
        self.assertIsNone(vendor_label("not_a_vendor"))


class TestTechnologyNormalization(unittest.TestCase):
    def test_product_prefix_maps_to_family(self):
        self.assertEqual(normalize_technology("UiPath Maestro").value, "uipath")
        self.assertEqual(normalize_technology("UiPath Robots").value, "uipath")
        self.assertEqual(normalize_technology("UiPath Test Cloud").value, "uipath")

    def test_regression_jira_service_management(self):
        # "service" is a product word, not a legal suffix — must not be stripped.
        self.assertEqual(normalize_technology("Jira Service Management").value, "jira_service_management")

    def test_product_names_map_to_their_canonical_key(self):
        self.assertEqual(normalize_technology("Amazon Elastic Kubernetes Service (EKS)").value, "eks")
        self.assertEqual(normalize_technology("Google Compute Engine").value, "compute_engine")
        self.assertEqual(normalize_technology("Oracle Fusion Cloud HCM").value, "oracle_fusion_hcm")
        self.assertEqual(normalize_technology("Adobe Experience Manager Sites").value, "aem_sites")
        self.assertEqual(normalize_technology("AWS Lambda").value, "lambda")

    def test_family_assignment(self):
        self.assertEqual(technology_family("jira_service_management"), "it_service")
        self.assertEqual(technology_family("bigquery"), "ml")
        self.assertEqual(technology_family("oracle_fusion"), "erp")

    def test_label_assignment(self):
        self.assertEqual(technology_label("jira_service_management"), "Jira Service Management")

    def test_unmapped_technology_keeps_raw(self):
        nv = normalize_technology("SabreMosaic")
        self.assertEqual(nv.confidence, 0.3)
        self.assertEqual(nv.raw, "SabreMosaic")


class TestBackfillPayload(unittest.TestCase):
    def _rec(self, vendors, software):
        return NS(
            id="rec-1",
            intervention_vendors=vendors,
            intervention_software=software,
        )

    def test_payload_shape_and_provenance(self):
        rec = self._rec(["AWS", "Amazon Web Services"], ["UiPath Maestro", "Jira"])
        payload = normalize_vendors_software(rec)
        self.assertEqual(len(payload["vendors"]), 2)
        self.assertEqual(len(payload["software"]), 2)

        aws_entry = payload["vendors"]["AWS"]
        self.assertEqual(aws_entry["value"], "aws")
        self.assertEqual(aws_entry["method"], "explicit")
        self.assertEqual(aws_entry["confidence"], 1.0)
        self.assertEqual(aws_entry["label"], "Amazon Web Services")
        self.assertEqual(aws_entry["version"], "vendor-v1")

        uipath_entry = payload["software"]["UiPath Maestro"]
        self.assertEqual(uipath_entry["value"], "uipath")
        self.assertEqual(uipath_entry["family"], "rpa")
        self.assertEqual(uipath_entry["label"], "UiPath")

    def test_empty_lists(self):
        rec = self._rec([], None)
        payload = normalize_vendors_software(rec)
        self.assertEqual(payload["vendors"], {})
        self.assertEqual(payload["software"], {})

    def test_deterministic(self):
        rec = self._rec(["AWS", "Oracle"], ["Jira", "BigQuery"])
        self.assertEqual(normalize_vendors_software(rec), normalize_vendors_software(rec))


if __name__ == "__main__":
    unittest.main()
