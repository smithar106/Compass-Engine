"""Tests for the enrichment pipeline: store, llm, validate, claim, workflow, benchmark."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass

from compass_agent.benchmark import run_benchmark
from compass_agent.claim import CollectorCandidateProvider, ClaimQueue
from compass_agent.daemon import BudgetTracker
from compass_agent.enrich import EnrichmentPipeline
from compass_agent.llm import EnrichmentResult, LLMClient
from compass_agent.publish import Publisher
from compass_agent.store import AgentStore
from compass_agent.validate import validate_enrichment
from compass_agent.workflow import EnrichmentWorkflow


def make_valid_payload(name="Acme Corp", category="AI", tier="silver", workflow="ticketing"):
    return {
        "organization_name": name,
        "workflow": workflow,
        "intervention_title": f"{category} {workflow} solution",
        "intervention_category": category,
        "evidence_tier": tier,
        "organization_employee_count": 5000,
        "outcomes": [{"metric_name": "resolution_time", "percentage_change": -40}],
        "outcome_block": {"percent_change": -40},
    }


class FakeLLM:
    """Deterministic LLM double for pipeline/workflow tests."""

    model = "fake-model"
    cost_per_call = 0.001
    input_tokens = 100
    output_tokens = 60

    def __init__(self, payload_factory=make_valid_payload):
        self._payload_factory = payload_factory
        self.calls = []

    @property
    def can_run(self):
        return True

    def estimate_cost(self, text):
        return 0.001 + len(text) / 4 * 0.00000014

    def enrich(self, text, title="", url=""):
        self.calls.append((text, title, url))
        return EnrichmentResult(
            payload=self._payload_factory(),
            cost=self.cost_per_call,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=self.model,
        )


class FakeProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    def list_candidates(self, limit):
        return self.candidates[:limit]


class TestAgentStore(unittest.TestCase):
    def test_claim_is_exclusive(self):
        store = AgentStore()
        c = {"id": "a", "record_id": "a", "doc_id": "d", "source": "s"}
        self.assertTrue(store.claim(c))
        self.assertFalse(store.claim(c))
        self.assertEqual(store.claimed_ids(), {"a"})

    def test_result_roundtrip(self):
        store = AgentStore()
        rid = store.save_result(
            "c1", make_valid_payload(), {"valid": True}, True, 0.01, 100, 60, "m"
        )
        self.assertTrue(rid)
        latest = store.latest_result("c1")
        self.assertEqual(latest["payload"]["organization_name"], "Acme Corp")
        self.assertTrue(latest["valid"])

    def test_benchmark_roundtrip(self):
        store = AgentStore()
        rid = store.save_benchmark("dry_run", {"precision": 0.5})
        self.assertTrue(rid)
        self.assertEqual(len(store.recent_benchmarks()), 1)


class TestLLMClient(unittest.TestCase):
    def test_cannot_run_without_key(self):
        llm = LLMClient(api_key="", provider="deepseek")
        self.assertFalse(llm.can_run)

    def test_estimate_cost_positive_with_key(self):
        llm = LLMClient(api_key="k", provider="deepseek")
        self.assertGreater(llm.estimate_cost("some text here"), 0.0)

    def test_no_key_estimate_zero(self):
        llm = LLMClient(api_key="", provider="deepseek")
        self.assertEqual(llm.estimate_cost("text"), 0.0)


class TestValidate(unittest.TestCase):
    def test_valid_payload(self):
        report = validate_enrichment(make_valid_payload())
        self.assertTrue(report.valid)
        self.assertEqual(report.issues, [])

    def test_missing_required_fields(self):
        report = validate_enrichment({"intervention_title": "x"})
        self.assertFalse(report.valid)
        self.assertTrue(any("organization_name" in i for i in report.issues))
        self.assertTrue(any("workflow" in i for i in report.issues))

    def test_invalid_category(self):
        report = validate_enrichment({**make_valid_payload(), "intervention_category": "Nope"})
        self.assertFalse(report.valid)
        self.assertTrue(any("intervention_category" in i for i in report.issues))

    def test_negative_employee_count(self):
        payload = make_valid_payload()
        payload["organization_employee_count"] = -5
        report = validate_enrichment(payload)
        self.assertFalse(report.valid)


class TestClaimQueue(unittest.TestCase):
    def test_batch_claims_only_unclaimed(self):
        store = AgentStore()
        provider = FakeProvider([
            {"id": "a", "record_id": "a", "text": "x" * 200, "title": ""},
            {"id": "b", "record_id": "b", "text": "y" * 200, "title": ""},
        ])
        queue = ClaimQueue(provider, store)
        first = queue.next_batch(1)
        self.assertEqual([c["id"] for c in first], ["a"])
        second = queue.next_batch(1)
        self.assertEqual([c["id"] for c in second], ["b"])


class TestCollectorCandidateProvider(unittest.TestCase):
    def _make_db(self, tmpdir):
        path = os.path.join(tmpdir, "collector.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, title TEXT, cleaned_text TEXT
            );
            CREATE TABLE intervention_records (
                id TEXT PRIMARY KEY, source_id TEXT, document_id TEXT,
                problem_statement TEXT, intervention_title TEXT,
                implementation_richness TEXT,
                implementation_field_provenance TEXT,
                organization_employee_count INTEGER,
                organization_geography TEXT,
                created_at TEXT
            );
            """
        )
        long_text = "A long source text. " * 40
        conn.execute("INSERT INTO documents VALUES (?,?,?)", ("d1", "Shopify story", long_text))
        conn.execute(
            "INSERT INTO intervention_records VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            ("r1", "src", "d1", "problem text", "title", "thin", "[]", None, None, "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO intervention_records VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            ("r2", "src", "d1", "problem", "title", "rich", "[]", 5000, '["United States"]', "2026-01-01"),
        )
        conn.commit()
        conn.close()
        return path

    def test_selects_only_thin_records_with_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_db(tmp)
            provider = CollectorCandidateProvider(path)
            candidates = provider.list_candidates(10)
            self.assertEqual([c["id"] for c in candidates], ["r1"])
            self.assertGreater(len(candidates[0]["text"]), 120)

    def test_missing_db_returns_empty(self):
        provider = CollectorCandidateProvider("/nonexistent/path.db")
        self.assertEqual(provider.list_candidates(5), [])


class TestPipeline(unittest.TestCase):
    def test_no_key_skips(self):
        class NoKeyLLM:
            model = "m"
            can_run = False

            def estimate_cost(self, text):
                return 0.0

        pipeline = EnrichmentPipeline(NoKeyLLM())
        outcome = pipeline.enrich_candidate({"id": "c", "text": "x" * 200})
        self.assertTrue(outcome.skipped)
        self.assertEqual(outcome.skip_reason, "no_api_key")

    def test_budget_gate_skips(self):
        pipeline = EnrichmentPipeline(FakeLLM())
        outcome = pipeline.enrich_candidate(
            {"id": "c", "text": "x" * 200}, budget_gate=lambda: False
        )
        self.assertTrue(outcome.skipped)
        self.assertEqual(outcome.skip_reason, "budget")

    def test_valid_enrichment(self):
        pipeline = EnrichmentPipeline(FakeLLM())
        outcome = pipeline.enrich_candidate({"id": "c", "text": "x" * 200})
        self.assertFalse(outcome.skipped)
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.cost, FakeLLM.cost_per_call)


class TestWorkflow(unittest.TestCase):
    def test_full_cycle_with_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            # collector DB to publish into
            cdb = os.path.join(tmp, "collector.db")
            conn = sqlite3.connect(cdb)
            conn.executescript(
                """
                CREATE TABLE intervention_records (
                    id TEXT PRIMARY KEY, intervention_title TEXT,
                    intervention_description TEXT, intervention_vendors TEXT,
                    intervention_components TEXT,
                    implementation_partner TEXT, implementation_pattern TEXT,
                    lessons_learned TEXT, change_management TEXT,
                    rollout_strategy TEXT, governance_model TEXT,
                    executive_sponsor TEXT, pilot_structure TEXT,
                    training_approach TEXT, adoption_approach TEXT,
                    implementation_team_structure TEXT, budget_range TEXT,
                    key_decision_makers TEXT, success_criteria TEXT,
                    organization_employee_count INTEGER,
                    organization_employee_band TEXT,
                    organization_geography TEXT,
                    review_status TEXT, implementation_richness TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO intervention_records (id, intervention_title, review_status)"
                " VALUES ('r1','','pending')"
            )
            conn.commit()
            conn.close()

            store = AgentStore()
            budget = BudgetTracker(max_daily=1.0, max_total=5.0)
            source_text = (
                "Acme Corp is headquartered in Canada and has 5000 employees. "
                "The ticketing workflow was automated with an AI solution." * 5
            )
            provider = FakeProvider([{"id": "c1", "record_id": "r1", "text": source_text, "title": "t"}])
            queue = ClaimQueue(provider, store)
            pipeline = EnrichmentPipeline(FakeLLM())
            publisher = Publisher(db_path=cdb, enabled=True)
            workflow = EnrichmentWorkflow(
                queue, pipeline, store, budget, publisher=publisher,
                concurrency=1, auto_publish=True,
            )

            report = workflow.run_cycle(cycle=1, max_docs=5)
            self.assertEqual(report.candidates, 1)
            self.assertEqual(report.processed, 1)
            self.assertEqual(report.valid, 1)
            self.assertEqual(report.published, 1)
            self.assertGreater(report.cost, 0)
            self.assertGreater(budget.total_spent, 0)
            # claim settled
            self.assertIn("c1", store.claimed_ids())
            # published into collector DB — including org backfill
            conn = sqlite3.connect(cdb)
            row = conn.execute(
                "SELECT review_status, implementation_richness,"
                " organization_employee_count, organization_employee_band,"
                " organization_geography FROM intervention_records WHERE id='r1'"
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "agent_enriched")
            self.assertEqual(row[1], "rich")
            self.assertEqual(row[2], 5000)          # employee count from LLM payload
            self.assertEqual(row[3], "1000-10000")  # derived band
            self.assertIn("Canada", (row[4] or ""))  # inferred geography from text

    def test_second_cycle_does_not_reprocess_claimed(self):
        store = AgentStore()
        budget = BudgetTracker(max_daily=1.0, max_total=5.0)
        provider = FakeProvider([{"id": "c1", "record_id": "r1", "text": "x" * 300, "title": ""}])
        queue = ClaimQueue(provider, store)
        workflow = EnrichmentWorkflow(
            queue, EnrichmentPipeline(FakeLLM()), store, budget, concurrency=1
        )
        r1 = workflow.run_cycle(1, 5)
        r2 = workflow.run_cycle(2, 5)
        self.assertEqual(r1.processed, 1)
        self.assertEqual(r2.candidates, 0)  # already claimed, not in store.claimed

    def test_budget_exhausted_skips_cycle(self):
        store = AgentStore()
        budget = BudgetTracker(max_daily=0.10, max_total=0.10)
        budget.spend(0.10)
        provider = FakeProvider([{"id": "c1", "record_id": "r1", "text": "x" * 300, "title": ""}])
        workflow = EnrichmentWorkflow(
            ClaimQueue(provider, store), EnrichmentPipeline(FakeLLM()), store, budget
        )
        report = workflow.run_cycle(1, 5)
        self.assertEqual(report.candidates, 0)
        self.assertTrue(report.failures)


class TestBenchmark(unittest.TestCase):
    def test_dry_run_reference_extractor(self):
        from compass_agent.benchmark import GOLD_SET

        store = AgentStore()

        def ref(text, title):
            lower = text.lower()
            p = make_valid_payload()
            if "shopify" in lower:
                p.update(organization_name="Shopify", intervention_category="Software",
                         workflow="commerce processing")
            if "chatbot" in lower:
                p.update(organization_name="regional bank", intervention_category="AI",
                         workflow="customer support")
            return p

        report = run_benchmark(ref, GOLD_SET, store=store, kind="dry_run")
        self.assertEqual(report["sample_size"], 2)
        self.assertGreaterEqual(report["recall"], 0.0)
        self.assertIn("precision", report)
        self.assertGreaterEqual(len(store.recent_benchmarks()), 1)


class TestHttpPublisher(unittest.TestCase):
    def test_active_requires_token_and_url(self):
        from compass_agent.publish import HttpPublisher

        self.assertFalse(HttpPublisher(api_url="", token="", enabled=True).active)
        self.assertFalse(HttpPublisher(api_url="http://x", token="", enabled=True).active)
        self.assertFalse(HttpPublisher(api_url="", token="t", enabled=True).active)
        self.assertTrue(HttpPublisher(api_url="http://x", token="t", enabled=True).active)
        self.assertFalse(HttpPublisher(api_url="http://x", token="t", enabled=False).active)

    def test_publishes_over_http(self):
        from unittest.mock import patch

        from compass_agent.publish import HttpPublisher

        publisher = HttpPublisher(api_url="https://engine.test", token="secret", enabled=True)
        with patch("httpx.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = "ok"
            n = publisher.publish(
                "rec-1",
                make_valid_payload(),
                source_text="headquartered in Canada with 5000 employees",
            )
        self.assertEqual(n, 1)
        args, kwargs = mock_post.call_args
        self.assertTrue(args[0].startswith("https://engine.test/api/evidence/enrichment"))
        self.assertEqual(kwargs["headers"]["X-Compass-Agent-Key"], "secret")
        self.assertEqual(kwargs["json"]["record_id"], "rec-1")
        self.assertIn("organization_employee_count", kwargs["json"]["fields"])

    def test_http_failure_returns_zero(self):
        from unittest.mock import patch

        from compass_agent.publish import HttpPublisher

        publisher = HttpPublisher(api_url="https://engine.test", token="secret", enabled=True)
        with patch("httpx.post") as mock_post:
            mock_post.return_value.status_code = 500
            mock_post.return_value.text = "boom"
            self.assertEqual(publisher.publish("rec-1", make_valid_payload()), 0)


class TestCliBenchmark(unittest.TestCase):
    def test_dry_run_exits_zero(self):
        from unittest.mock import patch

        from compass_agent.cli import main

        with patch.dict(
            os.environ,
            {"COMPASS_API_URL": "http://127.0.0.1:9"},
            clear=False,
        ):
            rc = main(["benchmark", "--dry-run"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
