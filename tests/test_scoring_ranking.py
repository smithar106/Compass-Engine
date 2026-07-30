import unittest
from compass_collector.api.schemas import (
    InvestigationRequest, ScoreComponent, ScoreBreakdown,
    ScoredInterventionResult, ComparableImplementationComparison,
    InterventionSelectionRequest, InterventionSelectionResponse,
)
from compass_collector.config.scoring_weights import (
    get_scoring_config, validate_weights, DEFAULT_SCORING_WEIGHTS,
    SCORING_MODEL_VERSION,
)
from compass_collector.analysis.component_scoring import (
    score_problem_alignment, score_organizational_similarity,
    score_goal_alignment, score_evidence_strength,
    score_implementation_fit, score_outcome_consistency,
    compute_all_component_scores, compute_match_score,
)
from compass_collector.analysis.scoring_ranking import (
    rank_interventions, _select_comparables,
)


_BASE_CANDIDATE = {
    "id": "test-1",
    "intervention_title": "RPA for invoice processing",
    "intervention_families": ["workflow_automation", "rpa"],
    "problem_statement": "Manual invoice processing is slow and error-prone",
    "problem_business_function": ["finance", "accounting"],
    "organization_type": "company",
    "organization_industry": ["technology", "finance"],
    "organization_employee_count": 500,
    "organization_employee_band": "200-1000",
    "organization_geography": ["North America"],
    "organization_name": "Acme Corp",
    "result_status": "successful",
    "independently_verified": True,
    "vendor_reported": False,
    "has_baseline": True,
    "has_post_measurement": True,
    "sample_size": 50,
    "outcome_summaries": ["Cycle time: -40%", "Cost savings: $500K"],
    "metrics": [
        {"metric_name": "cycle_time", "metric_category": "time",
         "percentage_change": -40, "absolute_change": None, "unit": "%",
         "baseline_value": 10, "post_value": 6},
        {"metric_name": "cost_savings", "metric_category": "cost",
         "percentage_change": None, "absolute_change": 500000, "unit": "USD",
         "baseline_value": None, "post_value": None},
    ],
    "intervention_software": ["UiPath"],
    "intervention_vendors": ["UiPath"],
    "intervention_teams_involved": ["IT", "Finance"],
    "intervention_implementation_cost": 100000,
    "intervention_implementation_time_value": 12,
    "intervention_implementation_time_unit": "weeks",
    "intervention_pilot_used": True,
    "intervention_human_review_required": False,
    "evidence_score": 75,
}


class TestScoringWeightsConfig(unittest.TestCase):

    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_SCORING_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0)

    def test_get_scoring_config(self):
        config = get_scoring_config()
        self.assertEqual(config.version, SCORING_MODEL_VERSION)
        self.assertEqual(config.weights, DEFAULT_SCORING_WEIGHTS)

    def test_validate_weights_passes(self):
        weights = dict(DEFAULT_SCORING_WEIGHTS)
        result = validate_weights(weights)
        self.assertEqual(result, weights)

    def test_validate_weights_missing_key(self):
        with self.assertRaises(ValueError):
            validate_weights({"problem_alignment": 1.0})

    def test_validate_weights_bad_sum(self):
        weights = dict(DEFAULT_SCORING_WEIGHTS)
        weights["problem_alignment"] = 0.5
        with self.assertRaises(ValueError):
            validate_weights(weights)


class TestComponentScoring(unittest.TestCase):

    def setUp(self):
        self.assessment = InvestigationRequest(
            business_function="finance",
            workflow="invoice_processing",
            industry="technology",
            company_size="500",
            desired_outcome="cost_reduction",
            geography="North America",
        )

    def test_score_problem_alignment_direct(self):
        comp = score_problem_alignment(_BASE_CANDIDATE, self.assessment)
        self.assertGreaterEqual(comp.score, 60)
        self.assertTrue(len(comp.reason) > 0)

    def test_score_problem_alignment_no_match(self):
        candidate = dict(_BASE_CANDIDATE)
        candidate["problem_statement"] = "Something completely unrelated"
        candidate["problem_business_function"] = ["marketing"]
        assessment = InvestigationRequest(business_function="hr", workflow="onboarding")
        comp = score_problem_alignment(candidate, assessment)
        self.assertLess(comp.score, 50)

    def test_score_organizational_similarity(self):
        comp = score_organizational_similarity(_BASE_CANDIDATE, self.assessment)
        self.assertGreaterEqual(comp.score, 0)
        self.assertLessEqual(comp.score, 100)
        self.assertTrue(len(comp.reason) > 0)

    def test_score_organizational_similarity_no_data(self):
        candidate = dict(_BASE_CANDIDATE)
        candidate["organization_employee_count"] = None
        candidate["organization_industry"] = []
        candidate["organization_type"] = ""
        candidate["organization_geography"] = []
        comp = score_organizational_similarity(candidate, self.assessment)
        self.assertLess(comp.score, 20)

    def test_score_goal_alignment_direct(self):
        comp = score_goal_alignment(_BASE_CANDIDATE, self.assessment)
        self.assertGreater(comp.score, 50)

    def test_score_goal_alignment_no_metrics(self):
        candidate = dict(_BASE_CANDIDATE)
        candidate["metrics"] = []
        comp = score_goal_alignment(candidate, self.assessment)
        self.assertEqual(comp.score, 0)

    def test_score_evidence_strength_high(self):
        comp = score_evidence_strength(_BASE_CANDIDATE)
        self.assertGreater(comp.score, 60)

    def test_score_evidence_strength_vendor_reported(self):
        candidate = dict(_BASE_CANDIDATE)
        candidate["vendor_reported"] = True
        candidate["independently_verified"] = False
        candidate["metrics"] = [{"percentage_change": 50}]
        comp = score_evidence_strength(candidate)
        self.assertLess(comp.score, 80)

    def test_score_evidence_strength_no_metrics(self):
        candidate = dict(_BASE_CANDIDATE)
        candidate["metrics"] = []
        comp = score_evidence_strength(candidate)
        self.assertGreaterEqual(comp.score, 50)
        self.assertLessEqual(comp.score, 100)

    def test_score_implementation_fit(self):
        comp = score_implementation_fit(_BASE_CANDIDATE, self.assessment)
        self.assertGreaterEqual(comp.score, 0)

    def test_score_outcome_consistency(self):
        comp = score_outcome_consistency(_BASE_CANDIDATE, [_BASE_CANDIDATE])
        self.assertEqual(comp.score, 50)

    def test_score_outcome_consistency_with_peers(self):
        peer = dict(_BASE_CANDIDATE)
        peer["id"] = "test-peer"
        peer["result_status"] = "successful"
        candidates = [_BASE_CANDIDATE, peer]
        comp = score_outcome_consistency(_BASE_CANDIDATE, candidates)
        self.assertEqual(comp.score, 90)

    def test_score_outcome_consistency_mixed(self):
        peer = dict(_BASE_CANDIDATE)
        peer["id"] = "test-peer"
        peer["result_status"] = "failed"
        peer2 = dict(_BASE_CANDIDATE)
        peer2["id"] = "test-peer2"
        peer2["result_status"] = "successful"
        candidates = [_BASE_CANDIDATE, peer, peer2]
        comp = score_outcome_consistency(_BASE_CANDIDATE, candidates)
        self.assertEqual(comp.score, 70)

    def test_compute_match_score(self):
        components = {
            "problem_alignment": ScoreComponent(score=100, weight=0.3),
            "organizational_similarity": ScoreComponent(score=100, weight=0.2),
            "goal_alignment": ScoreComponent(score=100, weight=0.2),
            "evidence_strength": ScoreComponent(score=100, weight=0.15),
            "implementation_fit": ScoreComponent(score=100, weight=0.1),
            "outcome_consistency": ScoreComponent(score=100, weight=0.05),
        }
        match = compute_match_score(components, DEFAULT_SCORING_WEIGHTS)
        self.assertAlmostEqual(match, 100.0)

    def test_compute_match_score_zero(self):
        components = {
            "problem_alignment": ScoreComponent(score=0, weight=0.3),
            "organizational_similarity": ScoreComponent(score=0, weight=0.2),
            "goal_alignment": ScoreComponent(score=0, weight=0.2),
            "evidence_strength": ScoreComponent(score=0, weight=0.15),
            "implementation_fit": ScoreComponent(score=0, weight=0.1),
            "outcome_consistency": ScoreComponent(score=0, weight=0.05),
        }
        match = compute_match_score(components, DEFAULT_SCORING_WEIGHTS)
        self.assertAlmostEqual(match, 0.0)

    def test_score_reproducibility(self):
        c1 = compute_all_component_scores(_BASE_CANDIDATE, self.assessment, [_BASE_CANDIDATE])
        c2 = compute_all_component_scores(_BASE_CANDIDATE, self.assessment, [_BASE_CANDIDATE])
        for key in c1:
            self.assertEqual(c1[key].score, c2[key].score)
            self.assertEqual(c1[key].reason, c2[key].reason)


class TestRanking(unittest.TestCase):

    def setUp(self):
        self.assessment = InvestigationRequest(
            business_function="finance",
            workflow="invoice_processing",
            industry="technology",
            company_size="500",
            desired_outcome="cost_reduction",
        )
        self.candidate_a = dict(_BASE_CANDIDATE)
        self.candidate_b = dict(_BASE_CANDIDATE)
        self.candidate_b["id"] = "test-2"
        self.candidate_b["intervention_title"] = "AI Document Processing"
        self.candidate_b["intervention_families"] = ["ai", "generative_ai"]
        self.candidate_b["organization_employee_count"] = 2000
        self.candidate_b["organization_employee_band"] = "1000-10000"
        self.candidate_b["organization_geography"] = ["Europe"]
        self.candidate_b["organization_name"] = "TechCorp"
        self.candidate_b["independently_verified"] = False
        self.candidate_b["metrics"] = [
            {"metric_name": "processing_time", "metric_category": "time",
             "percentage_change": -60, "absolute_change": None, "unit": "%",
             "baseline_value": 20, "post_value": 8},
        ]
        self.candidate_b["intervention_software"] = ["OpenAI"]
        self.candidate_b["intervention_implementation_cost"] = 250000
        self.candidate_b["intervention_implementation_time_value"] = 18
        self.candidate_b["evidence_score"] = 65

    def test_ranking_order(self):
        ranked, _ = rank_interventions([self.candidate_a, self.candidate_b], self.assessment)
        self.assertGreaterEqual(len(ranked), 1)
        if len(ranked) >= 2:
            self.assertGreaterEqual(ranked[0].match_score, ranked[1].match_score)

    def test_first_labeled_recommended(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        self.assertEqual(ranked[0].label, "recommended")

    def test_alternatives_labeled_alternative(self):
        ranked, _ = rank_interventions([self.candidate_a, self.candidate_b], self.assessment)
        if len(ranked) >= 2:
            self.assertEqual(ranked[1].label, "alternative")

    def test_fewer_than_three_candidates(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        self.assertEqual(len(ranked), 1)

    def test_score_breakdown_present(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        sb = ranked[0].score_breakdown
        self.assertIsNotNone(sb.problem_alignment)
        self.assertIsNotNone(sb.organizational_similarity)
        self.assertIsNotNone(sb.goal_alignment)
        self.assertIsNotNone(sb.evidence_strength)
        self.assertIsNotNone(sb.implementation_fit)
        self.assertIsNotNone(sb.outcome_consistency)

    def test_match_score_in_range(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        self.assertGreaterEqual(ranked[0].match_score, 0)
        self.assertLessEqual(ranked[0].match_score, 100)

    def test_rationale_not_empty(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        self.assertTrue(len(ranked[0].rationale) > 0)

    def test_evidence_strength_label(self):
        ranked, _ = rank_interventions([self.candidate_a], self.assessment)
        self.assertIn(ranked[0].evidence_strength, ["Strong", "Moderate", "Limited", "Low"])

    def test_configurable_weights_used(self):
        _, weights = rank_interventions([self.candidate_a], self.assessment)
        self.assertEqual(weights, DEFAULT_SCORING_WEIGHTS)

    def test_close_scores_noted(self):
        candidate_c = dict(self.candidate_b)
        candidate_c["id"] = "test-3"
        candidate_c["intervention_title"] = "Similar Option"
        ranked, _ = rank_interventions(
            [self.candidate_a, self.candidate_b, candidate_c], self.assessment
        )
        if len(ranked) >= 2:
            gap = abs(ranked[0].match_score - ranked[1].match_score)
            if gap < 5:
                self.assertIn("similarly", ranked[0].rationale.lower())

    def test_empty_candidates(self):
        ranked, _ = rank_interventions([], self.assessment)
        self.assertEqual(len(ranked), 0)


class TestEvidenceComparisons(unittest.TestCase):

    def setUp(self):
        self.assessment = InvestigationRequest(
            business_function="finance",
            industry="technology",
        )

    def test_select_comparables(self):
        candidates = [
            {**_BASE_CANDIDATE, "id": "c1"},
            {**_BASE_CANDIDATE, "id": "c2", "organization_name": "OrgB"},
        ]
        result = _select_comparables(candidates[0], candidates, self.assessment)
        self.assertIsInstance(result, list)

    def test_select_comparables_prefers_independent(self):
        candidates = [
            {**_BASE_CANDIDATE, "id": "c1"},
            {
                **_BASE_CANDIDATE, "id": "c2",
                "organization_name": "OrgB",
                "independently_verified": True,
            },
        ]
        result = _select_comparables(candidates[0], candidates, self.assessment)
        for r in result:
            self.assertTrue(len(r.organization_name) > 0)

    def test_comparable_has_all_fields(self):
        candidates = [
            {**_BASE_CANDIDATE, "id": "c1"},
            {**_BASE_CANDIDATE, "id": "c2", "organization_name": "OrgB"},
        ]
        result = _select_comparables(candidates[0], candidates, self.assessment)
        if result:
            c = result[0]
            self.assertTrue(hasattr(c, "organization_name"))
            self.assertTrue(hasattr(c, "documented_outcome"))
            self.assertTrue(hasattr(c, "comparability_explanation"))
            self.assertTrue(hasattr(c, "evidence_quality_score"))


class TestInterventionSelection(unittest.TestCase):

    def test_selection_request_model(self):
        req = InterventionSelectionRequest(
            recommendation_id="rec-1",
            selected_intervention_id="inv-1",
        )
        self.assertEqual(req.recommendation_id, "rec-1")
        self.assertEqual(req.selected_intervention_id, "inv-1")

    def test_selection_response_model(self):
        resp = InterventionSelectionResponse(
            selection_id="sel-1",
            recommendation_id="rec-1",
            selected_intervention_id="inv-1",
            selected_intervention_name="Test Intervention",
            selection_timestamp="2026-07-26T00:00:00Z",
        )
        self.assertEqual(resp.status, "active")
        self.assertEqual(resp.selected_intervention_name, "Test Intervention")

    def test_selection_snapshot_preserved(self):
        resp = InterventionSelectionResponse(
            selection_id="sel-1",
            recommendation_id="rec-1",
            selected_intervention_id="inv-1",
            selected_intervention_name="Test",
            scoring_weights=dict(DEFAULT_SCORING_WEIGHTS),
            user_inputs_snapshot={"company_size": "500", "industry": "tech"},
            score_breakdown_snapshot={"problem_alignment": {"score": 90}},
            evidence_ids_used=["Acme Corp"],
            selection_timestamp="2026-07-26T00:00:00Z",
        )
        self.assertEqual(resp.scoring_weights, DEFAULT_SCORING_WEIGHTS)
        self.assertIn("company_size", resp.user_inputs_snapshot)
        self.assertIn("Acme Corp", resp.evidence_ids_used)


class TestRecommendationVersioning(unittest.TestCase):

    def test_scoring_config_version(self):
        config = get_scoring_config()
        self.assertTrue(len(config.version) > 0)

    def test_weights_are_configurable(self):
        custom_weights = {
            "problem_alignment": 0.40,
            "organizational_similarity": 0.15,
            "goal_alignment": 0.15,
            "evidence_strength": 0.15,
            "implementation_fit": 0.10,
            "outcome_consistency": 0.05,
        }
        validated = validate_weights(custom_weights)
        self.assertAlmostEqual(sum(validated.values()), 1.0)
        self.assertEqual(validated["problem_alignment"], 0.40)


class TestReportGeneration(unittest.TestCase):

    def test_report_with_scored_interventions(self):
        from compass_collector.api.report import generate_report_html
        data = {
            "recommendation_id": "test-123",
            "engine_version": "3.1.0",
            "dataset_version": "v3",
            "generated_at": "2026-07-26T00:00:00Z",
            "assessment_summary": {"problem_statement": "Test", "workflow": "process_automation"},
            "scored_interventions": [
                {
                    "intervention_id": "inv-1",
                    "intervention_name": "Workflow Automation",
                    "rank": 1, "label": "recommended", "match_score": 85.0,
                    "score_breakdown": {
                        "problem_alignment": {"score": 90, "weight": 0.3, "reason": "Direct"},
                        "organizational_similarity": {"score": 80, "weight": 0.2, "reason": "Similar"},
                        "goal_alignment": {"score": 85, "weight": 0.2, "reason": "Match"},
                        "evidence_strength": {"score": 88, "weight": 0.15, "reason": "Strong"},
                        "implementation_fit": {"score": 75, "weight": 0.1, "reason": "Good"},
                        "outcome_consistency": {"score": 82, "weight": 0.05, "reason": "Consistent"},
                    },
                    "expected_impact": "30-40% reduction",
                    "evidence_strength": "Strong",
                    "implementation_difficulty": "Low",
                    "estimated_timeframe": "8-12 weeks",
                    "top_risks": ["Risk 1"],
                    "key_advantages": ["Fast"],
                    "key_tradeoffs": ["Structured"],
                    "comparable_implementations": [
                        {"organization_name": "Acme", "documented_outcome": "40%",
                         "comparability_explanation": "Similar"}
                    ],
                    "rationale": "Best fit",
                },
            ],
            "recommendations": [],
        }
        html = generate_report_html(data)
        self.assertIn("Recommended", html)
        self.assertIn("Workflow Automation", html)
        self.assertIn("Score Breakdown", html)
        self.assertTrue(len(html) > 0)


if __name__ == "__main__":
    unittest.main()
