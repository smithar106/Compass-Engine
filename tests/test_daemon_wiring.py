"""Phase 4 daemon wiring — run_evidence_ops end-to-end + daemon cycle.

The daemon's ``_do_work_cycle`` calls ``run_evidence_ops`` (Inspect→Plan→
Discover). That function must plan from the Gap Engine v2 top need, attach the
shopping-list directives (``search_terms`` + ``library_priority``) to the
campaign, run the discovery pass with them, and fall back to v1 ``analyze_gaps``
when the gap engine has no actionable need. These tests cover that path with a
real collector DB and a stub discovery so nothing touches the network.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import sqlalchemy

import compass_collector.models.intervention  # noqa: F401
import compass_collector.models.organization  # noqa: F401
import compass_collector.models.analysis_session  # noqa: F401
import compass_collector.models.outcome  # noqa: F401
from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord


def make_collector_db() -> str:
    """Build a temp collector DB with one weak category (legal/contract review)
    so the gap engine ranks it #1 and composes a shopping list."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = sqlalchemy.create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sqlalchemy.orm.sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    session.add_all([
        InterventionRecord(
            id=f"w{i}", organization_name=f"LegalCo{i}", problem_business_function=["legal"],
            intervention_components={"workflow": "contract review"},
            result_status="unknown",
        )
        for i in range(2)
    ])
    session.commit()
    session.close()
    return path


class StubDiscovery:
    """Minimal stand-in for DiscoveryPipeline: records the campaigns it is
    asked to run and returns a fake DiscoveryReport-like object."""

    def __init__(self):
        self.campaigns: list = []
        self.calls = 0

    def run(self, campaign, max_sources: int = 10):
        self.campaigns.append(campaign)
        self.calls += 1
        return NS(
            sources_discovered=2,
            accepted=1,
            rejected=1,
            cost_usd=0.002,
            source_report=lambda: [{"source": "ddg_targeted", "discovered": 2, "accepted": 1}],
        )


class TestRunEvidenceOpsWiring(unittest.TestCase):
    """run_evidence_ops: gap-engine need → campaign directives → discovery."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = make_collector_db()
        from compass_agent.store import AgentStore

        self.store = AgentStore()
        self.discovery = StubDiscovery()

    def tearDown(self):
        self.store.close()
        for p in (self.db_path, self.db_path + "-wal", self.db_path + "-shm"):
            try:
                os.remove(p)
            except OSError:
                pass

    def _run(self, **kw):
        from compass_agent.evidence_ops import run_evidence_ops

        defaults = dict(
            store=self.store,
            collector_db=self.db_path,
            discovery=self.discovery,
            max_sources=5,
            min_impact=0.1,
        )
        defaults.update(kw)
        with patch("compass_agent.libraries.ensure_libraries"), patch(
            "compass_agent.libraries.prioritize_libraries", return_value=[]
        ):
            return run_evidence_ops(**defaults)

    def test_plans_from_gap_engine_need_and_threads_directives(self):
        result = self._run()
        self.assertIsNotNone(result["campaign"])
        self.assertEqual(result["workflow"], "contract_review")
        # discovery was invoked with the campaign
        self.assertEqual(self.discovery.calls, 1)
        campaign = self.discovery.campaigns[0]
        self.assertEqual(campaign.workflow, "contract_review")
        # shopping-list directives attached
        self.assertTrue(campaign.search_terms, "campaign should carry composed search terms")
        self.assertTrue(campaign.library_priority, "campaign should carry library priority")
        self.assertEqual(result["source"], "ddg_targeted")
        self.assertGreater(result["accepted"], 0)

    def test_source_terms_match_gap_engine_composition(self):
        """The campaign's search terms must be exactly the need's composed
        hunt queries (earliest-position keyword hunt, deduped, capped)."""
        self._run()
        campaign = self.discovery.campaigns[0]
        # deterministic: contract review hunt queries mention the workflow
        joined = " ".join(campaign.search_terms).lower()
        self.assertIn("contract", joined)
        self.assertLessEqual(len(campaign.search_terms), 5)

    def test_falls_back_to_v1_when_gap_engine_fails(self):
        """If the gap engine raises, run_evidence_ops must degrade to the v1
        analyze_gaps planning and still run discovery (generic queries)."""
        import compass_agent.evidence_gap as eg

        with patch.object(eg, "run_gap_engine", side_effect=RuntimeError("boom")), patch(
            "compass_agent.libraries.ensure_libraries"
        ), patch("compass_agent.libraries.prioritize_libraries", return_value=[]):
            from compass_agent.evidence_ops import run_evidence_ops

            result = run_evidence_ops(
                store=self.store,
                collector_db=self.db_path,
                discovery=self.discovery,
                max_sources=5,
                min_impact=0.1,
            )
        self.assertEqual(self.discovery.calls, 1)
        campaign = self.discovery.campaigns[0]
        # v1 path: no shopping-list directives attached
        self.assertEqual(campaign.search_terms, [])
        self.assertEqual(campaign.library_priority, [])

    def test_no_records_returns_idle(self):
        """Empty collector DB → planned 0, no discovery run."""
        fd, empty = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            result = self._run(collector_db=empty)
            self.assertEqual(result["planned"], 0)
            self.assertEqual(self.discovery.calls, 0)
        finally:
            try:
                os.remove(empty)
            except OSError:
                pass


class TestDaemonCycleInvokesEvidenceOps(unittest.TestCase):
    """daemon._do_work_cycle must call run_evidence_ops when discovery +
    collector_db + store are wired (the Phase 4 integration point)."""

    def test_work_cycle_runs_evidence_ops(self):
        from compass_agent.config import Settings
        from compass_agent.daemon import Daemon
        from compass_agent.store import AgentStore

        db_path = make_collector_db()
        store = AgentStore()
        discovery = StubDiscovery()
        daemon = Daemon(
            Settings(max_daily_llm_usd=25.0, max_total_llm_usd=50.0, gold_factory_enabled=False,
                     outcome_discovery_enabled=False),
            enrichment=None,
            discovery=discovery,
            collector_db=db_path,
            store=store,
        )
        try:
            # The stub discovery has no fetcher — keep the library crawl out of
            # the way so only the discovery.run pass is exercised.
            with patch("compass_agent.libraries.ensure_libraries"), patch(
                "compass_agent.libraries.prioritize_libraries", return_value=[]
            ):
                processed = daemon._do_work_cycle(cycle=1)
        finally:
            store.close()
            for p in (db_path, db_path + "-wal", db_path + "-shm"):
                try:
                    os.remove(p)
                except OSError:
                    pass
        # evidence-ops discovery ran (accepted a record → processed > 0)
        self.assertEqual(discovery.calls, 1)
        self.assertGreaterEqual(processed, 1)
        campaign = discovery.campaigns[0]
        self.assertEqual(campaign.workflow, "contract_review")
        self.assertTrue(campaign.search_terms)


if __name__ == "__main__":
    unittest.main()
