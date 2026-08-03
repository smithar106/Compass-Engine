"""Tests for the Source Library architecture."""

from __future__ import annotations

import unittest

from compass_agent.campaign import Campaign
from compass_agent.discovery import DiscoveryPipeline, SourcePlanner, StubFetcher
from compass_agent.libraries import (
    LIBRARY_REGISTRY,
    ensure_libraries,
    prioritize_libraries,
    run_library,
)
from compass_agent.store import AgentStore
from compass_agent.acquisition import pick_strategy

from tests.test_evidence_ops import FakeLLM, StubIngest, StubSearch


class StubLibraryFetcher(StubFetcher):
    """Returns long article text for case-study pages, short for indexes."""

    def __init__(self, article_text=None):
        super().__init__(text="short index")
        self.article_text = article_text or ("A long case study article. " * 20)

    def fetch_links(self, url, title=""):
        return [
            {"url": f"https://stories.example.com/customer/{i}", "title": f"Customer {i}"}
            for i in range(1, 6)
        ]

    def fetch(self, url, title=""):
        if "customer" in url:
            return self.article_text
        return self.text


def make_pipeline():
    return DiscoveryPipeline(
        planner=SourcePlanner(backends=[StubSearch()]),
        fetcher=StubLibraryFetcher(),
        llm=FakeLLM(),
        ingest=StubIngest(accepted=True, rich=True),
    )


class TestLibraries(unittest.TestCase):
    def test_registry_is_registered(self):
        store = AgentStore()
        ensure_libraries(store)
        libs = store.list_libraries()
        self.assertGreaterEqual(len(libs), len(LIBRARY_REGISTRY))
        ids = {l["id"] for l in libs}
        self.assertIn("aws", ids)
        self.assertIn("gao", ids)

    def test_registry_is_idempotent(self):
        store = AgentStore()
        ensure_libraries(store)
        before = len(store.list_libraries())
        ensure_libraries(store)
        self.assertEqual(len(store.list_libraries()), before)

    def test_prioritize_ranks_unexplored_libraries_high(self):
        store = AgentStore()
        ensure_libraries(store)
        top = prioritize_libraries(store, max_libraries=3)
        self.assertEqual(len(top), 3)
        self.assertTrue(all(l["processed"] == 0 for l in top))  # unexplored prioritized

    def test_run_library_persists_progress_and_metrics(self):
        store = AgentStore()
        ensure_libraries(store)
        libs = store.list_libraries()
        aws = next(l for l in libs if l["id"] == "aws")
        campaign = Campaign(workflow="ticketing", business_function="support")
        result = run_library(store, aws, make_pipeline(), campaign, max_pages=2)

        # accepted records landed + library metrics updated
        self.assertGreater(result["accepted"], 0)
        updated = next(l for l in store.list_libraries() if l["id"] == "aws")
        self.assertGreater(updated["accepted"], 0)
        self.assertGreater(updated["processed"], 0)
        self.assertIsNotNone(updated["last_crawl"])
        # acceptance rate reflects accepted/processed
        self.assertGreater(updated["acceptance_rate"], 0)

    def test_run_library_does_not_reprocess_claimed_pages(self):
        store = AgentStore()
        ensure_libraries(store)
        aws = next(l for l in store.list_libraries() if l["id"] == "aws")
        run_library(store, aws, make_pipeline(), None, max_pages=2)
        processed_after_first = next(l for l in store.list_libraries() if l["id"] == "aws")["processed"]
        # second run processes a NEW batch of pending pages (no re-crawl of accepted/rejected)
        run_library(store, aws, make_pipeline(), None, max_pages=2)
        processed_after_second = next(l for l in store.list_libraries() if l["id"] == "aws")["processed"]
        self.assertGreater(processed_after_second, processed_after_first)


class TestAcquisitionSelection(unittest.TestCase):
    def test_preferred_strategy_used_by_default(self):
        lib = {"id": "aws", "acquisition": {"preferred": "fetchfox", "fallback": "static"}, "acquisition_stats": {}}
        self.assertEqual(pick_strategy(lib, AgentStore()), "fetchfox")

    def test_learns_to_fallback_after_zero_acceptances(self):
        lib = {
            "id": "aws",
            "acquisition": {"preferred": "fetchfox", "fallback": "static"},
            "acquisition_stats": {"fetchfox": {"runs": 2, "accepted": 0, "cost": 0.1, "pages": 10}},
        }
        self.assertEqual(pick_strategy(lib, AgentStore()), "static")

    def test_keeps_preferred_when_accepting(self):
        lib = {
            "id": "aws",
            "acquisition": {"preferred": "fetchfox", "fallback": "static"},
            "acquisition_stats": {"fetchfox": {"runs": 3, "accepted": 5, "cost": 0.1, "pages": 10}},
        }
        self.assertEqual(pick_strategy(lib, AgentStore()), "fetchfox")

    def test_structured_items_are_ingested_directly(self):
        """A FetchFox-style strategy returning structured implementation items
        should be validated + ingested without an intermediate fetch."""
        from unittest.mock import patch

        store = AgentStore()
        ensure_libraries(store)
        aws = next(l for l in store.list_libraries() if l["id"] == "aws")

        class StructuredStrategy:
            name = "fetchfox"

            def crawl(self, library, max_pages):
                return [
                    {
                        "organization_name": "FetchCorp",
                        "workflow": "ticketing",
                        "intervention_title": "AI support automation",
                        "intervention_category": "AI",
                        "evidence_tier": "silver",
                        "rollout_strategy": "Pilot then rollout",
                        "success_criteria": ["response < 1h"],
                        "lessons_learned": ["train early"],
                        "outcomes": [{"metric_name": "response_time", "category": "time", "percentage_change": -50}],
                    }
                ]

        with patch("compass_agent.acquisition.build_strategy", return_value=StructuredStrategy()):
            result = run_library(store, aws, make_pipeline(), None, max_pages=5)

        self.assertEqual(result["strategy"], "fetchfox")
        self.assertGreater(result["accepted"], 0)
        # learning stats recorded for the fetchfox strategy
        updated = next(l for l in store.list_libraries() if l["id"] == "aws")
        self.assertGreater((updated.get("acquisition_stats") or {}).get("fetchfox", {}).get("accepted", 0), 0)


if __name__ == "__main__":
    unittest.main()
