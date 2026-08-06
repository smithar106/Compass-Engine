"""Tests for the quality-first evidence operations (promote.py + evidence_graph.py)."""

from __future__ import annotations

import unittest

from compass_agent.evidence_graph import Edge, EdgeKind, EvidenceGraph, Node, NodeKind, normalize_id
from compass_agent.promote import (
    BRONZE_REASON_MISSING_OUTCOME,
    BRONZE_REASON_NEAR_DUPLICATE,
    BRONZE_REASON_THIN_IMPLEMENTATION,
    BRONZE_REASON_WEAK_PROVENANCE,
    audit_bronze,
    bronze_reasons,
    classify_tier,
    compute_points,
    plan_promotions,
    primary_bronze_reason,
    promotion_fields,
)


def rec(**over):
    d = {
        "id": "r-1",
        "organization_name": "Acme Corp",
        "organization_anonymized": False,
        "result_status": "unknown",
        "has_baseline": False,
        "problem_baseline_description": "",
        "intervention_measurement_period_value": None,
        "sample_size": None,
        "independently_verified": False,
        "vendor_reported": False,
        "source_id": "",
        "document_id": "",
        "implementation_provenance": "",
        "outcome_provenance": "",
        "implementation_richness": "",
        "evidence_level": "",
        "intervention_title": "RPA deployment",
        "intervention_components": {"source_url": "https://example.com/case-study"},
        "metrics": [],
    }
    d.update(over)
    return d


def with_metric(record, pct=None, absolute=None):
    record.setdefault("metrics", []).append(
        {"metric_name": "cost", "metric_category": "finance", "percentage_change": pct, "absolute_change": absolute}
    )
    return record


class TestComputePoints(unittest.TestCase):
    def test_weak_record_is_bronze(self):
        r = rec()  # real org (+2) only
        pts = compute_points(r)
        self.assertEqual(pts["score"], 2)
        self.assertEqual(pts["tier"], "bronze")
        self.assertEqual(classify_tier(r), "bronze")

    def test_strong_record_is_gold(self):
        r = rec(
            result_status="successful",
            has_baseline=True,
            intervention_measurement_period_value=12,
            sample_size=120,
            independently_verified=True,
        )
        with_metric(r, pct=-35)
        self.assertEqual(compute_points(r)["tier"], "gold")

    def test_vendor_only_downgraded(self):
        r = rec(vendor_reported=True)
        with_metric(r, pct=-20)
        # org(+2)+metric(+2)+vendor(-2) = 2 -> bronze
        self.assertEqual(compute_points(r)["tier"], "bronze")

    def test_academic_org_rejected(self):
        r = rec(organization_name="MIT University", independently_verified=False)
        self.assertEqual(compute_points(r)["tier"], "rejected")


class TestBronzeAudit(unittest.TestCase):
    def test_reason_classification(self):
        missing_metric = rec()
        reasons = bronze_reasons(missing_metric, [])
        self.assertTrue(reasons[BRONZE_REASON_MISSING_OUTCOME])
        self.assertTrue(reasons[BRONZE_REASON_WEAK_PROVENANCE])
        self.assertTrue(reasons[BRONZE_REASON_THIN_IMPLEMENTATION])
        self.assertEqual(primary_bronze_reason(missing_metric, []), BRONZE_REASON_MISSING_OUTCOME)

    def test_near_duplicate_detection(self):
        a = rec(id="a", intervention_title="AI ticketing automation")
        b = rec(id="b", intervention_title="AI ticketing system")
        c = rec(id="c", organization_name="Other Co", intervention_title="Warehouse robotics")
        self.assertTrue(bronze_reasons(b, [a, c])[BRONZE_REASON_NEAR_DUPLICATE])
        self.assertFalse(bronze_reasons(c, [a, b])[BRONZE_REASON_NEAR_DUPLICATE])

    def test_audit_totals(self):
        records = [rec(id=f"r{i}") for i in range(5)]
        audit = audit_bronze(records)
        self.assertEqual(audit.total_bronze, 5)
        self.assertEqual(sum(audit.reasons.values()), 5)

    def test_legacy_records_excluded_from_promotion(self):
        from compass_agent.promote import is_promotable, plan_promotions, promotion_readiness

        legacy = rec(id="legacy")  # default rec has source_url => promotable
        legacy["intervention_components"] = {}
        legacy["source_id"] = "compass_agent:discovery:abc"  # non-URL => legacy
        new_rec = rec(id="fresh")
        self.assertFalse(is_promotable(legacy))
        self.assertTrue(plan_promotions([legacy]) == [])
        readiness = promotion_readiness([legacy, new_rec])
        self.assertEqual(readiness["promotable"]["count"], 1)
        self.assertEqual(readiness["legacy_blocked"]["count"], 1)


class TestPlanPromotions(unittest.TestCase):
    def test_gap_and_fillable_computed(self):
        # Silver: org(+2) + deployed(+2) + measurable outcome(+2) = 6, gap to 8 = 2.
        r = with_metric(rec(result_status="completed"), pct=-10)
        self.assertEqual(compute_points(r)["score"], 6)
        promo = plan_promotions([r])[0]
        self.assertEqual(promo.current_score, 6)
        self.assertEqual(promo.gap, 2)
        self.assertIn("has_baseline", promo.fillable_missing)
        self.assertIn("has_sample_size", promo.fillable_missing)

    def test_fillable_ranks_first(self):
        same_score = with_metric(rec(id="same", result_status="completed"), pct=-10)
        # different org so they're independent; both score 4
        r1 = rec(id="fillable", result_status="completed")
        with_metric(r1, pct=-10)
        r2 = rec(
            id="blocked",
            result_status="completed",
            independently_verified=True,
            has_baseline=True,
            intervention_measurement_period_value=6,
            sample_size=50,
        )
        with_metric(r2, pct=-15)
        promos = plan_promotions([r1, r2])
        ids = [p.record_id for p in promos]
        self.assertEqual(ids[0], "fillable")


class TestPromotionFields(unittest.TestCase):
    def test_baseline_and_sample_recovered(self):
        r = with_metric(rec(result_status="completed"), pct=-10)
        from compass_agent.promote import Promotion

        promo = Promotion(
            record_id=r["id"], organization_name="Acme Corp", intervention_title="x",
            current_score=4, target_score=8, gap=4,
            missing=["has_baseline", "has_timeframe", "has_sample_size", "is_independent"],
            fillable_missing=["has_baseline", "has_sample_size"],
            non_fillable_missing=["is_independent"],
        )
        extraction = {"baseline": "Previously handled 40 tickets/day", "sample_size": 150}
        fields, metrics = promotion_fields(r, promo, extraction)
        self.assertIs(fields.get("has_baseline"), True)
        self.assertIn("problem_baseline_description", fields)
        self.assertEqual(fields.get("sample_size"), 150)
        self.assertEqual(metrics, [])

    def test_metrics_recovered(self):
        r = with_metric(rec(result_status="completed"), pct=-10)
        from compass_agent.promote import Promotion

        promo = Promotion(
            record_id=r["id"], organization_name="Acme Corp", intervention_title="x",
            current_score=4, target_score=8, gap=4,
            missing=["has_baseline", "has_measurable_outcome", "is_independent"],
            fillable_missing=["has_measurable_outcome", "has_baseline"],
            non_fillable_missing=["is_independent"],
        )
        extraction = {
            "outcomes": [{"metric_name": "resolve_time", "percentage_change": -40, "unit": "days"}],
            "baseline": "old baseline",
        }
        fields, metrics = promotion_fields(r, promo, extraction)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["metric_name"], "resolve_time")
        self.assertEqual(metrics[0]["percentage_change"], -40)

    def test_descriptive_timeframe_and_sample_recovered(self):
        """A non-numeric measurement_period and a descriptive sample_size from
        the LLM still map to engine fields (honours presence without inventing)."""
        from compass_agent.promote import Promotion

        r = with_metric(rec(result_status="completed"), pct=-10)
        promo = Promotion(
            record_id=r["id"], organization_name="Acme Corp", intervention_title="x",
            current_score=5, target_score=8, gap=3,
            missing=["has_timeframe", "has_sample_size"],
            fillable_missing=["has_timeframe", "has_sample_size"],
            non_fillable_missing=[],
        )
        extraction = {
            "measurement_period": {"value": "within weeks", "unit": "weeks"},
            "sample_size": "305,761 total contacts deflected across email and chat",
        }
        fields, metrics = promotion_fields(r, promo, extraction)
        self.assertEqual(fields.get("intervention_measurement_period_unit"), "weeks")
        self.assertGreaterEqual(float(fields.get("intervention_measurement_period_value")), 1)
        self.assertEqual(fields.get("sample_size"), 305761)
        self.assertEqual(metrics, [])


class TestEvidenceGraph(unittest.TestCase):
    def test_normalize_id(self):
        self.assertEqual(normalize_id(NodeKind.ORGANIZATION, "Acme Corp"), "organization:acme_corp")

    def test_graph_neighbors(self):
        g = EvidenceGraph()
        g.add_node(Node(id="o:acme", kind=NodeKind.ORGANIZATION, label="Acme"))
        g.add_node(Node(id="i:retail", kind=NodeKind.INDUSTRY, label="Retail"))
        g.add_edge(Edge(source="o:acme", target="i:retail", kind=EdgeKind.IN_INDUSTRY, record_id="r1"))
        g.add_edge(Edge(source="o:acme", target="o:other", kind=EdgeKind.HAS_PROBLEM, record_id="r1"))
        self.assertIn("i:retail", g.neighbors("o:acme", EdgeKind.IN_INDUSTRY))
        self.assertEqual(len(g.neighbors("o:acme", EdgeKind.IN_INDUSTRY)), 1)


if __name__ == "__main__":
    unittest.main()