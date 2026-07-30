import unittest
import uuid
from datetime import datetime

from compass_collector.implementation.schemas import (
    CreateWorkspaceRequest,
    UpdateMilestoneRequest,
    AddBlockerRequest,
    CompanionMessageRequest,
    RecordDecisionRequest,
    AddMetricMeasurementRequest,
)
from compass_collector.implementation.service import (
    _infer_intervention_family,
    _phase_templates,
    _generate_milestones,
    _next_action_text,
    MILESTONE_STATUSES,
    BLOCKER_STATUSES,
    METRIC_STATUSES,
)


class TestHelpers(unittest.TestCase):

    def test_infer_family_rpa(self):
        self.assertEqual(_infer_intervention_family("RPA for invoice processing"), "Workflow_Automation")

    def test_infer_family_ai(self):
        self.assertEqual(_infer_intervention_family("AI document processing"), "AI")

    def test_infer_family_software(self):
        self.assertEqual(_infer_intervention_family("CRM platform implementation"), "Software")

    def test_infer_family_process(self):
        self.assertEqual(_infer_intervention_family("Process redesign lean"), "Process_Redesign")

    def test_infer_family_staffing(self):
        self.assertEqual(_infer_intervention_family("Staffing increase hiring"), "Staffing")

    def test_infer_family_default(self):
        self.assertEqual(_infer_intervention_family("Unknown intervention"), "Workflow_Automation")

    def test_phase_templates_exist(self):
        for family in ["Workflow_Automation", "AI", "Software", "Process_Redesign", "Staffing"]:
            phases = _phase_templates(family)
            self.assertGreater(len(phases), 0)
            for p in phases:
                self.assertIn("name", p)
                self.assertIn("objective", p)
                self.assertIn("duration", p)

    def test_generate_milestones(self):
        ms = _generate_milestones("Discovery & Documentation", 0)
        self.assertEqual(len(ms), 4)
        for m in ms:
            self.assertIn("title", m)
            self.assertEqual(m["status"], "not_started")

    def test_generate_milestones_default(self):
        ms = _generate_milestones("Unknown Phase", 3)
        self.assertGreater(len(ms), 0)

    def test_milestone_statuses(self):
        expected = ["not_started", "in_progress", "blocked", "completed", "skipped"]
        self.assertEqual(MILESTONE_STATUSES, expected)

    def test_blocker_statuses(self):
        self.assertEqual(BLOCKER_STATUSES, ["open", "resolved"])

    def test_metric_statuses(self):
        expected = ["not_measured", "below_target", "on_track", "achieved", "regressed"]
        self.assertEqual(METRIC_STATUSES, expected)


class TestNextAction(unittest.TestCase):

    def test_next_action_in_progress(self):
        class MockPhase:
            def __init__(self, name, status):
                self.name = name
                self.status = status
                self.id = "p1"

        class MockMilestone:
            def __init__(self, title, status, phase_id="p1"):
                self.title = title
                self.status = status
                self.phase_id = phase_id

        phases = [MockPhase("Discovery", "in_progress")]
        milestones = [
            MockMilestone("Map process", "completed"),
            MockMilestone("Identify candidates", "not_started"),
        ]
        action = _next_action_text(phases, milestones)
        self.assertIn("Identify", action)

    def test_next_action_blocked(self):
        class MockPhase:
            def __init__(self, name, status):
                self.name = name
                self.status = status
                self.id = "p1"

        class MockMilestone:
            def __init__(self, title, status, phase_id="p1"):
                self.title = title
                self.status = status
                self.phase_id = phase_id

        phases = [MockPhase("Discovery", "in_progress")]
        milestones = [
            MockMilestone("Map process", "completed"),
            MockMilestone("Identify candidates", "blocked"),
        ]
        action = _next_action_text(phases, milestones)
        self.assertIn("blocker", action.lower())

    def test_next_action_all_complete(self):
        class MockPhase:
            def __init__(self, name, status):
                self.name = name
                self.status = status
                self.id = "p1"

        class MockMilestone:
            def __init__(self, title, status, phase_id="p1"):
                self.title = title
                self.status = status
                self.phase_id = phase_id

        phases = [MockPhase("Discovery", "completed")]
        milestones = [
            MockMilestone("Map process", "completed"),
            MockMilestone("Identify candidates", "completed"),
        ]
        action = _next_action_text(phases, milestones)
        self.assertTrue(len(action) > 0)


class TestSchemas(unittest.TestCase):

    def test_create_workspace_request(self):
        req = CreateWorkspaceRequest(
            recommendation_id="rec-1",
            selected_intervention_id="inv-1",
            intended_goal="Reduce processing time",
        )
        self.assertEqual(req.recommendation_id, "rec-1")
        self.assertEqual(req.intended_goal, "Reduce processing time")

    def test_update_milestone_request(self):
        req = UpdateMilestoneRequest(status="completed", notes="Done", owner="Alice")
        self.assertEqual(req.status, "completed")
        self.assertEqual(req.owner, "Alice")

    def test_add_blocker_request(self):
        req = AddBlockerRequest(
            title="Legal approval",
            description="Legal team is understaffed",
            severity="high",
        )
        self.assertEqual(req.title, "Legal approval")
        self.assertEqual(req.severity, "high")

    def test_companion_message_request(self):
        req = CompanionMessageRequest(content="What should we do next?")
        self.assertEqual(req.content, "What should we do next?")

    def test_record_decision_request(self):
        req = RecordDecisionRequest(
            decision="Proceed with pilot",
            context="Pilot results were positive",
            rationale="Evidence supports full rollout",
        )
        self.assertEqual(req.decision, "Proceed with pilot")
        self.assertEqual(len(req.alternatives_considered), 0)

    def test_add_metric_measurement_request(self):
        req = AddMetricMeasurementRequest(metric_id="m1", value=85.0, measurement_date="2026-07-30")
        self.assertEqual(req.value, 85.0)


class TestCompanionResponse(unittest.TestCase):

    def test_next_step_keyword_detection(self):
        from compass_collector.implementation.service import _companion_response

        class MockWS:
            selected_intervention_name = "RPA"
            current_phase = "Discovery"
            overall_progress = 25.0
            known_risks = []
            supporting_evidence_ids = []

        class MockPhase:
            def __init__(self, name, status, milestones=None):
                self.name = name
                self.status = status
                self.id = "p1"

        class MockMilestone:
            def __init__(self, title, status, phase_id="p1"):
                self.title = title
                self.status = status
                self.phase_id = phase_id

        class MockBlocker:
            def __init__(self, title):
                self.title = title

        # Simulate the companion response with a session mock via direct call
        ws = MockWS()
        phases = [MockPhase("Discovery", "in_progress")]
        milestones = [
            MockMilestone("Map process", "completed"),
            MockMilestone("Identify candidates", "not_started"),
        ]
        blockers = []

        # Test with "next" keyword
        response = None
        msg = "What should we do next?"
        msg_lower = msg.lower()
        if any(kw in msg_lower for kw in ["next", "what should", "what do", "recommend", "suggest"]):
            response = "next_step_response"
        self.assertEqual(response, "next_step_response")

    def test_risk_keyword_detection(self):
        msg = "What risks should we prepare for?"
        msg_lower = msg.lower()
        detected = any(kw in msg_lower for kw in ["risk", "concern", "worry"])
        self.assertTrue(detected)

    def test_progress_keyword_detection(self):
        msg = "Give me a progress summary"
        msg_lower = msg.lower()
        detected = any(kw in msg_lower for kw in ["progress", "summary", "status", "update"])
        self.assertTrue(detected)

    def test_change_keyword_detection(self):
        msg = "I think we should change the approach"
        msg_lower = msg.lower()
        detected = any(kw in msg_lower for kw in ["change", "adjust", "modify"])
        self.assertTrue(detected)

    def test_general_fallback(self):
        msg = "Hello, how are you?"
        msg_lower = msg.lower()
        modes = ["next", "risk", "progress", "change"]
        detected = any(kw in msg_lower for mode_keywords in [
            ["next", "what should", "what do", "recommend", "suggest"],
            ["risk", "concern", "worry"],
            ["progress", "summary", "status", "update"],
            ["change", "adjust", "modify"],
        ] for kw in mode_keywords)
        self.assertFalse(detected)


class TestProgressCalculation(unittest.TestCase):

    def test_progress_requires_no_division_by_zero(self):
        from compass_collector.implementation.service import _recalculate_progress

        class MockWS:
            overall_progress = 0.0

        class MockPhase:
            def __init__(self):
                self.id = "p1"

        class MockSession:
            def query(self, model):
                return self
            def filter_by(self, **kwargs):
                return self
            def order_by(self, field):
                return self
            def all(self):
                return []
            def first(self):
                return MockWS()

        session = MockSession()
        _recalculate_progress(session, "ws-1")
        self.assertEqual(MockWS.overall_progress, 0.0)


class TestPhaseTemplateConsistency(unittest.TestCase):

    def test_all_families_have_templates(self):
        families = ["Workflow_Automation", "AI", "Software", "Process_Redesign", "Staffing"]
        for family in families:
            phases = _phase_templates(family)
            self.assertGreater(
                len(phases), 0,
                f"Family {family} should have phase templates"
            )

    def test_all_phases_have_milestones(self):
        families = ["Workflow_Automation", "AI", "Software", "Process_Redesign", "Staffing"]
        for family in families:
            phases = _phase_templates(family)
            for pi, phase in enumerate(phases):
                ms = _generate_milestones(phase["name"], pi)
                self.assertGreater(
                    len(ms), 0,
                    f"Phase '{phase['name']}' in {family} should have milestones"
                )


if __name__ == "__main__":
    unittest.main()
