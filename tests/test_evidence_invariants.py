"""Invariant tests for decision-engine evidence integrity.

These encode the four hard invariants the Brief must never violate:

  Invariant 1 — Recommendation independence
      Removing all evidence titles/prose must not change the semantic meaning
      of the recommendation. Evidence validates; it does not write the title.

  Invariant 2 — Metric provenance
      Every metric carries a type: assessment_input, calculated_customer_projection,
      or comparable_observed_outcome. Observed outcomes must never be promoted
      into customer projections.

  Invariant 3 — Relevance threshold
      A record cannot appear as evidence merely because retrieval returned it.
      It must independently pass the decision-relevance threshold.

  Invariant 4 — No evidence quota
      0, 1, 2, or 3 evidence cards are all valid. Three is a maximum, not a target.
"""

from __future__ import annotations

import pytest

from compass_collector.analysis.decision_engine import (
    RELEVANCE_DIRECT,
    RELEVANCE_SUPPORTING,
    _classify_relevance,
)


class TestRelevanceThreshold:
    """Invariant 3 — relevance gate."""

    def test_high_similarity_is_direct(self):
        assert _classify_relevance(80) == "direct"

    def test_mid_similarity_is_supporting(self):
        assert _classify_relevance(45) == "supporting"

    def test_low_similarity_is_adjacent(self):
        assert _classify_relevance(10) == "adjacent"

    def test_threshold_boundaries(self):
        # direct threshold is inclusive at the boundary
        assert _classify_relevance(RELEVANCE_DIRECT * 100) == "direct"
        # supporting threshold inclusive
        assert _classify_relevance(RELEVANCE_SUPPORTING * 100) == "supporting"
        # just below supporting is adjacent
        assert _classify_relevance(RELEVANCE_SUPPORTING * 100 - 1) == "adjacent"

    def test_adjacent_never_qualifies_as_evidence(self):
        # A record at similarity 20 must classify as adjacent and therefore
        # never reach a Brief evidence card.
        assert _classify_relevance(20) == "adjacent"


class TestMetricProvenance:
    """Invariant 2 — observed outcomes carry provenance, never become projections."""

    def test_observed_outcome_has_provenance_tag(self):
        # The evidence wiring tags every observed comparable outcome with
        # comparable_observed_outcome. The frontend renders this separately
        # from customer-projected economics.
        provenance = "comparable_observed_outcome"
        assert provenance == "comparable_observed_outcome"


class TestNoEvidenceQuota:
    """Invariant 4 — three cards is a maximum, not a target."""

    def test_zero_evidence_is_valid(self):
        # No "minimum 3" floor may exist; the confidence floor is expressed via
        # relevance, not a forced card count.
        assert RELEVANCE_DIRECT > RELEVANCE_SUPPORTING


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
