"""Tests for Evidence Operations: gap analysis, campaign planning, discovery."""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from compass_agent.gap_analysis import analyze_gaps
from compass_agent.campaign import CampaignPlanner
from compass_agent.discovery import (
    _clean_url,
    DiscoveryPipeline,
    SourcePlanner,
    StubFetcher,
    build_queries,
)
from compass_agent.store import AgentStore


def record(workflow="invoice_processing", bf="finance", tier="bronze",
           rollout="", success=None, lessons=None, pattern=None, idx=0):
    return NS(
        id=f"r-{workflow}-{idx}",
        intervention_components={"workflow": workflow},
        problem_business_function=[bf],
        evidence_level=tier,
        rollout_strategy=rollout,
        success_criteria=success or [],
        lessons_learned=lessons or [],
        implementation_pattern=pattern or [],
    )


class FakeLLM:
    model = "fake"
    can_run = True

    def __init__(self, tier="silver", workflow="invoice_processing"):
        self.tier = tier
        self.workflow = workflow

    def enrich(self, text, title="", url=""):
        from compass_agent.llm import EnrichmentResult

        payload = {
            "organization_name": "Discovered Corp",
            "workflow": self.workflow,
            "intervention_title": "AP automation",
            "intervention_category": "Workflow_Automation",
            "evidence_tier": self.tier,
            "business_function": "finance",
            "business_problem": "manual invoice processing",
            "rollout_strategy": "Pilot then phased rollout",
            "success_criteria": ["cycle time < 2 days"],
            "lessons_learned": ["train champions"],
            "implementation_pattern": ["Pilot -> Rollout"],
            "outcomes": [{"metric_name": "cycle_time", "category": "time", "percentage_change": -60}],
            "evidence_quality": {"implementation_provenance": "customer_documented", "outcome_provenance": "independently_verified"},
        }
        return EnrichmentResult(payload=payload, cost=0.001, input_tokens=100, output_tokens=50, model=self.model)

    def enrich_many(self, text, title="", url=""):
        from compass_agent.llm import EnrichmentResult

        items = [
            {"organization_name": "Org A", "workflow": self.workflow, "intervention_title": "Automation A",
             "intervention_category": "Workflow_Automation", "evidence_tier": "silver",
             "rollout_strategy": "Pilot", "success_criteria": ["x"], "lessons_learned": ["y"],
             "implementation_pattern": ["Pilot -> Rollout"], "outcomes": []},
            {"organization_name": "Org B", "workflow": self.workflow, "intervention_title": "Automation B",
             "intervention_category": "Workflow_Automation", "evidence_tier": "bronze",
             "rollout_strategy": "Big bang", "success_criteria": ["z"], "lessons_learned": [],
             "implementation_pattern": ["Big Bang"], "outcomes": []},
        ]
        return [EnrichmentResult(payload=p, cost=0.002, input_tokens=200, output_tokens=100, model=self.model) for p in items]


class RejectingLLM(FakeLLM):
    """LLM whose single extraction always fails validation (roundup page)."""

    def enrich(self, text, title="", url=""):
        from compass_agent.llm import EnrichmentResult

        return EnrichmentResult(
            payload={"evidence_tier": "rejected", "rejection_reason": "roundup"},
            cost=0.001, input_tokens=100, output_tokens=50, model=self.model,
        )


class StubIngest:
    def __init__(self, accepted=True, rich=True):
        self.accepted = accepted
        self.rich = rich

    @property
    def active(self):
        return True

    def ingest(self, record):
        if self.accepted:
            return {"accepted": True, "record_id": "new-1", "rich": self.rich}
        return {"accepted": False, "reason": "insufficient_depth"}


class StubSearch:
    def __init__(self, results=None):
        self.results = results or [
            {"url": "https://example.com/a", "title": "Case study A"},
            {"url": "https://example.com/b", "title": "Case study B"},
        ]

    def search(self, query, max_results=10):
        return self.results[:max_results]


class TestGapAnalysis(unittest.TestCase):
    def test_ranks_by_expected_impact(self):
        records = [
            # healthy category: many records, gold, good field coverage
            record(workflow="invoice_processing", bf="finance", tier="gold", rollout="r", success=["s"], lessons=["l"], pattern=["p"], idx=0),
            record(workflow="invoice_processing", bf="finance", tier="silver", rollout="r", success=["s"], lessons=["l"], pattern=["p"], idx=1),
            record(workflow="invoice_processing", bf="finance", tier="silver", rollout="r", success=["s"], lessons=["l"], pattern=["p"], idx=2),
            record(workflow="invoice_processing", bf="finance", tier="silver", rollout="r", success=["s"], lessons=["l"], pattern=["p"], idx=3),
            record(workflow="invoice_processing", bf="finance", tier="silver", rollout="r", success=["s"], lessons=["l"], pattern=["p"], idx=4),
            # sparse category: 1 record, no implementation fields
            record(workflow="onboarding", bf="customer_success", tier="bronze", idx=0),
            record(workflow="onboarding", bf="customer_success", tier="bronze", idx=1),
        ]
        gaps = analyze_gaps(records)
        by_wf = {g.workflow: g for g in gaps}
        self.assertIn("invoice_processing", by_wf)
        self.assertIn("onboarding", by_wf)
        # onboarding is sparser → higher gap score
        self.assertGreater(by_wf["onboarding"].gap_score, by_wf["invoice_processing"].gap_score)
        self.assertTrue(by_wf["onboarding"].missing_fields)
        self.assertGreater(by_wf["onboarding"].estimated_records_needed, 0)
        # expected impact = gap * demand (onboarding demand 0.8)
        self.assertAlmostEqual(by_wf["onboarding"].expected_impact, by_wf["onboarding"].gap_score * 0.8, places=3)

    def test_deterministic(self):
        records = [record(workflow="ticketing", bf="support", idx=i) for i in range(3)]
        a = analyze_gaps(records)
        b = analyze_gaps(records)
        self.assertEqual([g.to_dict() for g in a], [g.to_dict() for g in b])


class TestCampaignPlanner(unittest.TestCase):
    def test_plans_and_persists_campaigns(self):
        store = AgentStore()
        gaps = analyze_gaps([record(workflow="onboarding", bf="customer_success", idx=i) for i in range(2)])
        planner = CampaignPlanner(store, min_impact=0.0, top_n=1)
        campaigns = planner.plan(gaps)
        self.assertEqual(len(campaigns), 1)
        c = campaigns[0]
        self.assertEqual(c.workflow, "onboarding")
        self.assertEqual(c.status, "planned")
        self.assertTrue(c.source_types)
        self.assertGreater(c.expected_impact, 0)
        # persisted
        stored = store.list_campaigns()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], c.id)


class TestDiscovery(unittest.TestCase):
    def test_clean_url_decodes_duckduckgo_redirect(self):
        url = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.com%2Fcase-study&rut=abc"
        cleaned = _clean_url(url)
        self.assertEqual(cleaned, "https://www.example.com/case-study")
        # plain protocol-relative → https:
        self.assertEqual(_clean_url("//example.com/x"), "https://example.com/x")
        # already absolute unchanged
        self.assertEqual(_clean_url("https://example.com/x"), "https://example.com/x")

    def test_build_queries_targets_workflow(self):
        queries = build_queries("invoice_processing", ["vendor_case_study"])
        self.assertTrue(queries)
        joined = " ".join(queries).lower()
        self.assertIn("invoice", joined)

    def test_pipeline_reports_and_updates_campaign(self):
        from compass_agent.campaign import Campaign

        store = AgentStore()
        campaign = Campaign(workflow="invoice_processing", business_function="finance")
        pipeline = DiscoveryPipeline(
            planner=SourcePlanner(backends=[StubSearch()], max_per_query=2),
            fetcher=StubFetcher(text="A long case study text about invoice processing automation. " * 10),
            llm=FakeLLM(),
            ingest=StubIngest(accepted=True, rich=True),
            budget_gate=lambda: True,
        )
        report = pipeline.run(campaign, max_sources=3)
        self.assertGreater(report.sources_discovered, 0)
        self.assertGreater(report.accepted, 0)
        self.assertGreater(report.cost_usd, 0)
        # campaign counters updated
        self.assertGreater(campaign.accepted, 0)
        self.assertGreater(campaign.discovered, 0)

    def test_rejected_when_ingest_refuses(self):
        from compass_agent.campaign import Campaign

        campaign = Campaign(workflow="ticketing", business_function="support")
        pipeline = DiscoveryPipeline(
            planner=SourcePlanner(backends=[StubSearch()]),
            fetcher=StubFetcher(text="A long source text about ticketing. " * 10),
            llm=FakeLLM(),
            ingest=StubIngest(accepted=False),
        )
        report = pipeline.run(campaign, max_sources=2)
        self.assertGreater(report.sources_discovered, 0)
        self.assertEqual(report.accepted, 0)
        self.assertGreater(report.rejected, 0)
        self.assertEqual(campaign.accepted, 0)

    def test_budget_gate_stops(self):
        from compass_agent.campaign import Campaign

        campaign = Campaign(workflow="ticketing", business_function="support")
        pipeline = DiscoveryPipeline(
            planner=SourcePlanner(backends=[StubSearch()]),
            fetcher=StubFetcher(text="A long source text about ticketing. " * 10),
            llm=FakeLLM(),
            ingest=StubIngest(),
            budget_gate=lambda: False,
        )
        report = pipeline.run(campaign, max_sources=2)
        self.assertEqual(report.accepted, 0)
        self.assertIn("budget_gate", report.rejections)

    def test_multi_extraction_mines_roundup_pages(self):
        """A roundup page that single-extraction rejects should yield multiple
        accepted implementations via enrich_many."""
        from compass_agent.campaign import Campaign

        campaign = Campaign(workflow="ticketing", business_function="support")
        pipeline = DiscoveryPipeline(
            planner=SourcePlanner(backends=[StubSearch()]),
            fetcher=StubFetcher(text="A long roundup page describing many orgs. " * 10),
            llm=RejectingLLM(),
            ingest=StubIngest(accepted=True, rich=True),
        )
        report = pipeline.run(campaign, max_sources=2)
        self.assertGreater(report.accepted, 0)  # mined Org A + Org B
        self.assertGreaterEqual(report.accepted, 2)
        self.assertEqual(campaign.accepted, report.accepted)


if __name__ == "__main__":
    unittest.main()
