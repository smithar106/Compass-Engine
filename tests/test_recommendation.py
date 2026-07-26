"""Tests for the recommendation service — outcome ranges, estimate policy, ranking."""
import unittest
from compass_collector.api.schemas import (
    InvestigationRequest, ComparableEvidence, OutcomeRange,
    WhyRankedFirst, SpecificIntervention, Assumption, NextValidationStep,
)
from compass_collector.api.service import (
    _estimate_impact, _calculate_outcome_ranges, _generate_specific_action,
    _generate_specific_intervention, _build_ranking_explanation,
    _build_assumptions_detail, _build_information_gaps, _build_next_validation_step,
    _normalize_metric_name, _normalize_metric_value, _is_company_wide_metric,
)
from compass_collector.api.report import generate_report_html


def _make_comparable(org: str, tier: str, metrics: list[dict]) -> ComparableEvidence:
    return ComparableEvidence(
        record_id=org,
        organization=org,
        intervention="Test intervention",
        evidence_tier=tier,
        normalized_metrics=metrics,
        outcome_summary="; ".join(f"{m['metric']}: {m['value']}" for m in metrics),
    )


class TestEstimateImpact(unittest.TestCase):

    def test_insufficient_input_when_missing_volume(self):
        req = InvestigationRequest(people_involved="", workflow_frequency="")
        comparables = [_make_comparable("OrgA", "silver", [{"metric": "Cycle time", "value": "30%"}])]
        savings, hours = _estimate_impact(comparables, "Workflow_Automation", req)
        self.assertEqual(savings.status, "insufficient_input")
        self.assertEqual(hours.status, "insufficient_input")
        self.assertIn("missing_inputs", savings.model_dump())

    def test_missing_inputs_listed(self):
        req = InvestigationRequest(people_involved="10", workflow_frequency="Daily")
        comparables = [_make_comparable("OrgA", "bronze", [{"metric": "Cycle time", "value": "30%"}])]
        savings, hours = _estimate_impact(comparables, "Workflow_Automation", req)
        self.assertEqual(savings.status, "insufficient_input")
        self.assertGreater(len(savings.missing_inputs), 0)

    def test_what_can_be_reported_when_comparables_exist(self):
        req = InvestigationRequest()
        comparables = [_make_comparable("OrgA", "silver", [{"metric": "Cycle time", "value": "30%"}])]
        savings, _ = _estimate_impact(comparables, "Workflow_Automation", req)
        self.assertTrue("evidence-derived" in savings.what_can_be_reported.lower())


class TestOutcomeRanges(unittest.TestCase):

    def test_single_metric(self):
        c = [_make_comparable("OrgA", "gold", [{"metric": "Cycle time", "value": "30%"}])]
        ranges = _calculate_outcome_ranges(c)
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].sample_size, 1)
        self.assertEqual(ranges[0].calculation_method, "single_value")

    def test_multiple_comparable_metrics(self):
        c = [
            _make_comparable("OrgA", "gold", [{"metric": "Cycle time", "value": "30%"}]),
            _make_comparable("OrgB", "silver", [{"metric": "Cycle time", "value": "40%"}]),
            _make_comparable("OrgC", "bronze", [{"metric": "Cycle time", "value": "25%"}]),
        ]
        ranges = _calculate_outcome_ranges(c)
        self.assertEqual(len(ranges), 1)
        r = ranges[0]
        self.assertEqual(r.sample_size, 3)
        self.assertEqual(r.direction, "reduction")
        self.assertTrue(r.directly_comparable)
        self.assertIsNotNone(r.median)

    def test_incompatible_units_excluded(self):
        c = [
            _make_comparable("OrgA", "gold", [{"metric": "Cost savings", "value": "$50000"}]),
            _make_comparable("OrgB", "silver", [{"metric": "Cost savings", "value": "20%"}]),
        ]
        ranges = _calculate_outcome_ranges(c)
        if ranges:
            self.assertFalse(ranges[0].directly_comparable)

    def test_company_wide_metrics_excluded(self):
        c = [_make_comparable("OrgA", "gold", [{"metric": "Company-wide cost savings", "value": "$10M"}])]
        ranges = _calculate_outcome_ranges(c)
        self.assertEqual(len(ranges), 0)

    def test_source_record_ids(self):
        c = [_make_comparable("OrgA", "gold", [{"metric": "Cycle time", "value": "30%"}])]
        ranges = _calculate_outcome_ranges(c)
        self.assertTrue(len(ranges[0].source_record_ids) > 0)


class TestMetricNormalization(unittest.TestCase):

    def test_company_wide_detection(self):
        self.assertTrue(_is_company_wide_metric("company-wide cost savings"))
        self.assertTrue(_is_company_wide_metric("enterprise-wide revenue"))
        self.assertFalse(_is_company_wide_metric("cost savings"))

    def test_normalize_name(self):
        self.assertEqual(_normalize_metric_name("cycle_time"), "Cycle time")
        self.assertEqual(_normalize_metric_name("error_rate"), "Error rate")

    def test_normalize_value(self):
        self.assertEqual(_normalize_metric_value("30%"), "30%")
        self.assertEqual(_normalize_metric_value("$50,000"), "$50,000")


class TestSpecificAction(unittest.TestCase):

    def test_falls_back_to_top_example(self):
        inv = {
            "family_id": "Workflow_Automation",
            "top_examples": [{"intervention": "Custom intake automation with approval routing"}],
        }
        req = InvestigationRequest()
        action = _generate_specific_action(inv, req)
        self.assertIn("intake automation", action.lower())

    def test_category_based_generation(self):
        inv = {"family_id": "AI", "top_examples": []}
        req = InvestigationRequest(problem_statement="Missing inbound calls")
        action = _generate_specific_action(inv, req)
        self.assertIn("AI", action)

    def test_software_intervention(self):
        inv = {"family_id": "Software", "top_examples": []}
        req = InvestigationRequest()
        action = _generate_specific_action(inv, req)
        self.assertIn("centralized", action.lower())

    def test_specific_intervention_object(self):
        inv = {"family_id": "Workflow_Automation", "top_examples": []}
        req = InvestigationRequest(problem_statement="Manual contract review")
        si = _generate_specific_intervention(inv, req)
        self.assertIsInstance(si, SpecificIntervention)
        self.assertTrue(len(si.title) > 0)
        self.assertTrue(len(si.required_changes) > 0)
        self.assertTrue(len(si.scope_boundaries) > 0)


class TestRankingExplanation(unittest.TestCase):

    def test_returns_none_without_recs(self):
        self.assertIsNone(_build_ranking_explanation([], []))

    def test_has_summary_and_reasons(self):
        from compass_collector.api.schemas import Recommendation, EvidenceSummary, Confidence, ImpactSummary
        rec = Recommendation(
            rank=1,
            title="Workflow Automation",
            category="Workflow_Automation",
            evidence_summary=EvidenceSummary(total_comparables=5, gold_count=2, average_evidence_score=75),
            confidence=Confidence(score=0.75, label="strong"),
            impact=ImpactSummary(),
        )
        wrf = _build_ranking_explanation([rec], [])
        self.assertIsNotNone(wrf)
        self.assertTrue(len(wrf.summary) > 0)


class TestAssumptionsAndGaps(unittest.TestCase):

    def test_assumptions_created_when_few_comparables(self):
        inv = {"confidence": 50}
        req = InvestigationRequest(people_involved="", workflow_frequency="")
        assumptions = _build_assumptions_detail(inv, [], req)
        self.assertGreater(len(assumptions), 0)

    def test_information_gaps_created(self):
        inv = {}
        req = InvestigationRequest()
        gaps = _build_information_gaps(inv, [], req)
        self.assertGreater(len(gaps), 0)

    def test_next_step_created(self):
        ns = _build_next_validation_step(1, "Workflow_Automation", 2, InvestigationRequest())
        self.assertIsNotNone(ns)
        self.assertTrue(len(ns.action) > 0)
        self.assertTrue(len(ns.purpose) > 0)
        self.assertTrue(len(ns.owner) > 0)
        self.assertTrue(len(ns.required_inputs) > 0)
        self.assertTrue(len(ns.success_criteria) > 0)


class TestLargeOutcomeContext(unittest.TestCase):

    def test_large_currency_flagged(self):
        from compass_collector.api.service import _add_large_outcome_context
        ctx = _add_large_outcome_context("Cost savings", 50_000_000, "currency")
        self.assertIn("scale", ctx)
        self.assertEqual(ctx["used_in_estimate"], False)

    def test_small_currency_not_flagged(self):
        from compass_collector.api.service import _add_large_outcome_context
        ctx = _add_large_outcome_context("Cost savings", 5000, "currency")
        self.assertEqual(ctx, {})


class TestReportGeneration(unittest.TestCase):

    def test_report_html_generates(self):
        data = {
            "recommendation_id": "test-123",
            "engine_version": "3.0.0",
            "dataset_version": "v3",
            "generated_at": "2026-07-26T00:00:00Z",
            "assessment_summary": {"problem_statement": "Test problem", "workflow": "process_automation"},
            "recommendations": [
                {
                    "rank": 1,
                    "title": "Workflow Automation",
                    "category": "Workflow_Automation",
                    "specific_action": "Automate intake routing",
                    "outcome_ranges": [],
                    "confidence": {"score": 0.7, "label": "strong"},
                    "evidence_summary": {"total_comparables": 5, "gold_count": 2, "silver_count": 1, "bronze_count": 2, "average_evidence_score": 70},
                    "risks": [],
                    "comparable_implementations": [],
                    "assumptions_detail": [],
                    "information_gaps": [],
                }
            ],
            "methodology_summary": "Test methodology",
        }
        html = generate_report_html(data)
        self.assertTrue(len(html) > 0)
        self.assertIn("Compass Recommendation", html)
        self.assertIn("Automate intake routing", html)


if __name__ == "__main__":
    unittest.main()
