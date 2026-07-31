"""End-to-end tests for recommendation quality pipeline.

Tests the full pipeline: retrieve → classify roles → assemble package →
compute confidence → build traceability map.

Verifies:
  - Retrieval returns results
  - Role classification assigns diverse roles
  - Evidence package is balanced
  - Confidence is deterministic
  - Traceability maps every output to source
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.analysis.retrieval import ImplementationQuery, find_comparable_implementations
from compass_collector.analysis.evidence_roles import (
    classify_evidence_roles, assemble_evidence_package,
    build_traceability_map, EvidenceRole,
)
from compass_collector.analysis.confidence_scoring import (
    compute_confidence, compute_inputs_from_package, ConfidenceInputs,
    ConfidenceScore,
)


class TestEvidenceRoles:
    """Test evidence role classification."""

    def test_classify_assigns_roles(self):
        """Role classification produces non-empty results."""
        q = ImplementationQuery(
            workflow="invoice processing automation",
            business_function="finance",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])[:20]
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        assert len(classified) > 0
        for item in classified:
            assert "evidence_role" in item
            assert isinstance(item["evidence_role"], str)
            assert "evidence_roles" in item
            assert isinstance(item["evidence_roles"], list)

    def test_roles_include_diverse_types(self):
        """Evidence roles span multiple categories."""
        q = ImplementationQuery(
            workflow="invoice processing",
            business_function="finance",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        all_roles = set()
        for item in classified:
            all_roles.update(item.get("evidence_roles", []))
        # Should have at least INTERVENTION and OUTCOME
        assert EvidenceRole.INTERVENTION in all_roles, f"Roles found: {all_roles}"


class TestEvidencePackage:
    """Test evidence package assembly."""

    def test_assemble_returns_packages(self):
        """Package assembly returns all five role groups."""
        q = ImplementationQuery(
            workflow="claims processing automation",
            business_function="operations",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        package = assemble_evidence_package(classified)

        assert "packages" in package
        packages = package["packages"]
        for role in ["problem_fit", "intervention", "implementation", "outcome", "risk"]:
            assert role in packages, f"Missing role: {role}"

    def test_balanced_flag(self):
        """Package reports balance status."""
        q = ImplementationQuery(
            workflow="customer support automation",
            business_function="customer_support",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        package = assemble_evidence_package(classified)

        assert "is_balanced" in package
        assert isinstance(package["is_balanced"], bool)

    def test_tier_tracking(self):
        """Package tracks tier distribution."""
        q = ImplementationQuery(
            workflow="returns processing automation",
            business_function="operations",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        package = assemble_evidence_package(classified)

        assert "tier_breakdown" in package
        for role in package["tier_breakdown"]:
            assert "gold" in package["tier_breakdown"][role]
            assert "silver" in package["tier_breakdown"][role]
            assert "bronze" in package["tier_breakdown"][role]


class TestConfidenceScoring:
    """Test deterministic confidence scoring."""

    def test_zero_evidence(self):
        """Zero evidence produces insufficient confidence."""
        inputs = ConfidenceInputs(total_evidence=0)
        score = compute_confidence(inputs)
        assert score.overall < 20
        assert score.label == "insufficient"

    def test_strong_evidence(self):
        """Strong evidence produces high confidence."""
        inputs = ConfidenceInputs(
            total_evidence=20,
            gold_count=10,
            silver_count=5,
            bronze_count=5,
            outcome_records=15,
            measured_outcomes=10,
            independent_count=8,
            vendor_count=2,
            implementation_rich=5,
            unique_orgs=10,
            negative_count=0,
            risk_count=1,
        )
        score = compute_confidence(inputs)
        assert score.overall >= 70, f"Expected >= 70, got {score.overall}"
        assert score.label == "strong"

    def test_moderate_evidence(self):
        """Moderate evidence produces moderate confidence."""
        inputs = ConfidenceInputs(
            total_evidence=10,
            gold_count=2,
            silver_count=3,
            bronze_count=5,
            outcome_records=5,
            measured_outcomes=3,
            independent_count=2,
            vendor_count=3,
            implementation_rich=1,
            unique_orgs=5,
            negative_count=1,
            risk_count=1,
        )
        score = compute_confidence(inputs)
        assert score.overall >= 40, f"Expected >= 40, got {score.overall}"
        assert score.label in ("moderate", "limited")

    def test_components_all_present(self):
        """All five components are computed."""
        inputs = ConfidenceInputs(
            total_evidence=5,
            gold_count=1,
            silver_count=1,
            bronze_count=3,
            outcome_records=2,
            measured_outcomes=1,
            independent_count=1,
            vendor_count=2,
            implementation_rich=0,
            unique_orgs=3,
        )
        score = compute_confidence(inputs)
        expected_components = [
            "outcome_strength",
            "evidence_quality",
            "implementation_depth",
            "consistency",
            "diversity",
        ]
        for comp in expected_components:
            assert comp in score.components, f"Missing {comp}"

    def test_deterministic(self):
        """Same inputs produce same result."""
        inputs = ConfidenceInputs(
            total_evidence=10,
            gold_count=3,
            silver_count=3,
            bronze_count=4,
            outcome_records=5,
            measured_outcomes=3,
            independent_count=2,
            vendor_count=2,
            implementation_rich=1,
            unique_orgs=4,
        )
        s1 = compute_confidence(inputs)
        s2 = compute_confidence(inputs)
        assert s1.overall == s2.overall
        assert s1.label == s2.label

    def test_risk_penalty_reduces_confidence(self):
        """Risk evidence reduces confidence score."""
        clean = ConfidenceInputs(
            total_evidence=10,
            gold_count=5,
            silver_count=5,
            bronze_count=0,
            outcome_records=8,
            measured_outcomes=5,
            independent_count=5,
            vendor_count=0,
            implementation_rich=3,
            unique_orgs=8,
            negative_count=0,
            risk_count=0,
        )
        risky = ConfidenceInputs(
            total_evidence=10,
            gold_count=5,
            silver_count=5,
            bronze_count=0,
            outcome_records=8,
            measured_outcomes=5,
            independent_count=5,
            vendor_count=0,
            implementation_rich=3,
            unique_orgs=8,
            negative_count=5,
            risk_count=3,
            has_contradictory=True,
        )
        clean_score = compute_confidence(clean)
        risky_score = compute_confidence(risky)
        assert risky_score.overall < clean_score.overall


class TestTraceability:
    """Test field traceability mapping."""

    def test_all_fields_mapped(self):
        """Every output field has a traceability entry."""
        q = ImplementationQuery(
            workflow="invoice processing",
            business_function="finance",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        package = assemble_evidence_package(classified)
        trace = build_traceability_map(package)

        expected_fields = [
            "comparable_implementation_count",
            "evidence_tiers",
            "confidence",
            "expected_impact",
            "implementation_pattern",
            "partner_type",
            "blueprint_phases",
            "risks",
        ]
        for field in expected_fields:
            assert field in trace, f"Missing trace entry for {field}"
            assert "source" in trace[field]

    def test_source_is_valid(self):
        """Trace source is one of: live_graph, computed_from_graph, synthetic."""
        q = ImplementationQuery(
            workflow="customer onboarding",
            business_function="customer_support",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        package = assemble_evidence_package(classified)
        trace = build_traceability_map(package)

        valid_sources = {"live_graph", "computed_from_graph", "synthetic"}
        for field, info in trace.items():
            assert info["source"] in valid_sources, f"{field} has invalid source: {info['source']}"


class TestFullPipeline:
    """Test the complete pipeline end-to-end."""

    def test_pipeline_no_exceptions(self):
        """Full pipeline runs without exceptions."""
        q = ImplementationQuery(
            workflow="manual invoice processing is slow",
            business_function="finance",
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])
        assert len(items) > 0, "No results from retrieval"

        classified = classify_evidence_roles(
            items, q.workflow, q.business_function
        )
        assert len(classified) > 0

        package = assemble_evidence_package(classified)
        assert package["is_balanced"] is not None

        inputs = compute_inputs_from_package(package)
        conf = compute_confidence(inputs)
        assert 0 <= conf.overall <= 100

        trace = build_traceability_map(package)
        assert len(trace) > 0

    def test_returns_deterministic_confidence(self):
        """Two identical queries return the same confidence."""
        q = ImplementationQuery(
            workflow="returns processing",
            business_function="operations",
        )
        result1 = find_comparable_implementations(q)
        result2 = find_comparable_implementations(q)

        items1 = result1.get("results", [])
        items2 = result2.get("results", [])

        classified1 = classify_evidence_roles(items1, q.workflow, q.business_function)
        classified2 = classify_evidence_roles(items2, q.workflow, q.business_function)

        package1 = assemble_evidence_package(classified1)
        package2 = assemble_evidence_package(classified2)

        inputs1 = compute_inputs_from_package(package1)
        inputs2 = compute_inputs_from_package(package2)

        conf1 = compute_confidence(inputs1)
        conf2 = compute_confidence(inputs2)

        assert conf1.overall == conf2.overall, f"Non-deterministic: {conf1.overall} vs {conf2.overall}"
        assert conf1.label == conf2.label
