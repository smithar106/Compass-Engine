"""Tests for the fail-closed evidence-mode gate (P1).

Verifies that only fully verified, sourced evidence can be presented as
verified; that unsourced records never are; and that the recommendation-level
mode is derived correctly.
"""

from __future__ import annotations

import unittest

import compass_collector.models.intervention  # noqa: F401 — registers table for conftest migration
from compass_collector.analysis.evidence_mode import (
    ClaimKind,
    EvidenceMode,
    claim_kind_for_modes,
    classify_evidence_mode,
    dominant_mode,
    is_presentable_as_verified,
)


class TestClassifyEvidenceMode(unittest.TestCase):
    def test_claim_verified_with_source_is_verified(self):
        self.assertEqual(
            classify_evidence_mode("claim_verified", "https://sec.gov/x"),
            EvidenceMode.VERIFIED,
        )

    def test_claim_verified_without_source_is_not_verified(self):
        # Fail-closed: no source → cannot be verified.
        self.assertEqual(
            classify_evidence_mode("claim_verified", ""),
            EvidenceMode.INSUFFICIENT,
        )

    def test_legacy_with_source_is_exploratory(self):
        self.assertEqual(
            classify_evidence_mode("legacy", "https://example.com/case-study"),
            EvidenceMode.EXPLORATORY,
        )

    def test_source_authentic_with_source_is_exploratory(self):
        self.assertEqual(
            classify_evidence_mode("source_authentic", "https://example.com/x"),
            EvidenceMode.EXPLORATORY,
        )

    def test_document_verified_with_source_is_exploratory(self):
        self.assertEqual(
            classify_evidence_mode("document_verified", "https://example.com/x"),
            EvidenceMode.EXPLORATORY,
        )

    def test_no_source_is_insufficient(self):
        self.assertEqual(classify_evidence_mode("legacy", ""), EvidenceMode.INSUFFICIENT)

    def test_rejected_is_insufficient(self):
        self.assertEqual(
            classify_evidence_mode("rejected", "https://example.com/x"),
            EvidenceMode.INSUFFICIENT,
        )

    def test_none_values_fail_closed(self):
        self.assertEqual(classify_evidence_mode(None, None), EvidenceMode.INSUFFICIENT)


class TestPresentableAsVerified(unittest.TestCase):
    def test_only_claim_verified_with_source_passes(self):
        self.assertTrue(is_presentable_as_verified("claim_verified", "https://sec.gov/x"))
        self.assertFalse(is_presentable_as_verified("legacy", "https://example.com/x"))
        self.assertFalse(is_presentable_as_verified("claim_verified", ""))
        self.assertFalse(is_presentable_as_verified("document_verified", "https://x.gov/y"))
        self.assertFalse(is_presentable_as_verified(None, None))


class TestDominantMode(unittest.TestCase):
    def test_all_verified_is_verified(self):
        self.assertEqual(
            dominant_mode([EvidenceMode.VERIFIED, EvidenceMode.VERIFIED]),
            EvidenceMode.VERIFIED,
        )

    def test_mixed_verified_and_exploratory_is_exploratory(self):
        # Not all verified → never claim verified.
        self.assertEqual(
            dominant_mode([EvidenceMode.VERIFIED, EvidenceMode.EXPLORATORY]),
            EvidenceMode.EXPLORATORY,
        )

    def test_any_exploratory_is_exploratory(self):
        self.assertEqual(
            dominant_mode([EvidenceMode.EXPLORATORY, EvidenceMode.INSUFFICIENT]),
            EvidenceMode.EXPLORATORY,
        )

    def test_all_insufficient_is_insufficient(self):
        self.assertEqual(
            dominant_mode([EvidenceMode.INSUFFICIENT, EvidenceMode.INSUFFICIENT]),
            EvidenceMode.INSUFFICIENT,
        )

    def test_empty_is_insufficient(self):
        self.assertEqual(dominant_mode([]), EvidenceMode.INSUFFICIENT)


class TestClaimKind(unittest.TestCase):
    def test_verified_support_is_finding(self):
        self.assertEqual(
            claim_kind_for_modes([EvidenceMode.VERIFIED]), ClaimKind.FINDING
        )

    def test_exploratory_only_is_hypothesis(self):
        self.assertEqual(
            claim_kind_for_modes([EvidenceMode.EXPLORATORY]), ClaimKind.HYPOTHESIS
        )

    def test_no_evidence_is_hypothesis(self):
        self.assertEqual(claim_kind_for_modes([]), ClaimKind.HYPOTHESIS)


if __name__ == "__main__":
    unittest.main()
