"""Phase 2/4 tests for the Workflow Recovery Worker.

Covers: candidate selection (unknown workflows only), source-text resolution,
LLM-phrase → canonical mapping (incl. taxonomy candidates for unmapped
phrases), idempotent writes, and the dry-run path. Uses a temp-file DB +
injected fake LLM — no network, no keys.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace as NS
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord

from compass_agent.workflow_recovery import (
    _candidate,
    _map_recovered,
    _source_text,
    run_workflow_recovery,
)


class _FakeLLM:
    """Injected LLM returning fixed payloads per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, text, system, user, title, url):
        self.calls += 1
        resp = self._responses.pop(0) if self._responses else {"workflow": None}
        return NS(payload=resp, cost=0.0002)


def _make_db(records):
    """Create a temp-file DB seeded with the given intervention records."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from compass_collector.models.document import Document  # register before create_all

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    for r in records:
        s.add(InterventionRecord(**r))
    # Attach document bodies so the worker's source-text gate passes.
    body = ("This document describes the implementation in detail. " * 30)
    s.add(Document(id="doc2", url="https://example.com/picsart", cleaned_text=body + "customer service call handling"))
    s.add(Document(id="doc3", url="https://example.com/oracle", cleaned_text=body + "contract review and legal document processing"))
    s.commit()
    s.close()
    return path


def _records():
    return [
        dict(id="r1", organization_name="Acme", intervention_title="Invoice automation",
             problem_statement="AP took 30 days",
             problem_business_function=["finance"],
             intervention_components={"workflow": "invoice processing"},  # already canonical
             workflow_normalized={"value": "invoice_processing", "confidence": 1.0}),
        dict(id="r2", organization_name="Beta", intervention_title="Picsart case study | Google Cloud",
             problem_statement="", problem_business_function=["operations"], document_id="doc2",
             intervention_components={}, workflow_normalized={"value": "uncategorized", "confidence": 0.2}),
        dict(id="r3", organization_name="Gamma", intervention_title="Oracle CX suite implementation",
             problem_statement="", problem_business_function=["operations"], document_id="doc3",
             intervention_components={}, workflow_normalized={"value": "uncategorized", "confidence": 0.2}),
    ]


class TestCandidateSelection(unittest.TestCase):
    def test_unknown_workflow_is_candidate(self):
        self.assertTrue(_candidate(NS(workflow_normalized={})))
        self.assertTrue(_candidate(NS(workflow_normalized={"value": "uncategorized", "confidence": 0.2})))
        self.assertTrue(_candidate(NS(workflow_normalized=None)))

    def test_known_workflow_not_candidate(self):
        self.assertFalse(_candidate(NS(workflow_normalized={"value": "invoice_processing", "confidence": 0.85})))


class TestMapping(unittest.TestCase):
    def test_maps_canonical_phrase(self):
        entry = _map_recovered("Invoice processing")
        self.assertEqual(entry["value"], "invoice_processing")
        self.assertEqual(entry["function"], "finance")
        self.assertEqual(entry["source"], "llm_recovery")
        self.assertEqual(entry["confidence"], 0.85)

    def test_maps_free_text_phrase(self):
        entry = _map_recovered("customer service call handling")
        self.assertEqual(entry["value"], "call_routing")

    def test_unmapped_phrase_returns_none(self):
        self.assertIsNone(_map_recovered("Zz exotic quantum melding"))

    def test_null_returns_none(self):
        self.assertIsNone(_map_recovered(None))
        self.assertIsNone(_map_recovered(""))


class TestSourceText(unittest.TestCase):
    def test_empty_when_no_document_and_no_url(self):
        session = object()
        rec = NS(document_id=None, intervention_components={})
        self.assertEqual(_source_text(session, rec), "")


class TestWorkerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db(_records())

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_skips_known_records(self):
        fake = _FakeLLM([{"workflow": "customer service call handling"}, {"workflow": "contract review"}])
        report = run_workflow_recovery(
            self.db_path, api_key="test", llm=fake, max_applications=5, limit=10
        )
        # r1 skipped (known) → only r2, r3 processed
        self.assertEqual(report["candidates"], 2)
        self.assertEqual(fake.calls, 2)
        self.assertEqual(report["recovered"], 2)

    def test_writes_canonical_workflows(self):
        fake = _FakeLLM([{"workflow": "invoice invoicing"}] * 3)
        report = run_workflow_recovery(self.db_path, api_key="test", llm=fake, max_applications=5, limit=10)
        self.assertEqual(report["recovered"], 2)
        engine = create_engine(f"sqlite:///{self.db_path}")
        Session = sessionmaker(bind=engine)
        s = Session()
        r2 = s.get(InterventionRecord, "r2")
        self.assertEqual(r2.workflow_normalized["value"], "invoice_processing")
        self.assertEqual(r2.workflow_normalized["source"], "llm_recovery")
        self.assertEqual(r2.workflow_normalized["function"], "finance")
        s.close()

    def test_unmapped_phrase_reported_as_taxonomy_candidate(self):
        fake = _FakeLLM([{"workflow": "Zz exotic quantum melding"}, {"workflow": None}])
        report = run_workflow_recovery(self.db_path, api_key="test", llm=fake, max_applications=5, limit=10)
        self.assertEqual(report["recovered"], 0)
        self.assertEqual(report["unmapped"], 1)
        self.assertIn("Zz exotic quantum melding", report["taxonomy_candidates"])

    def test_dry_run_calls_nothing(self):
        report = run_workflow_recovery(self.db_path, api_key="", dry_run=True, max_applications=5, limit=10)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["candidates"], 2)  # r2 + r3
        self.assertEqual(report["applied"], 0)

    def test_no_api_key_skips(self):
        report = run_workflow_recovery(self.db_path, api_key="", max_applications=5, limit=10)
        self.assertEqual(report["skipped"], "no_api_key")

    def test_unmapped_records_marked_not_recandidated(self):
        """Unmapped outcomes must leave the candidate set (no re-burn)."""
        from compass_agent.workflow_recovery import _candidate

        fake = _FakeLLM([{"workflow": "Zz exotic quantum melding"}, {"workflow": "Zz exotic quantum melding"}])
        report = run_workflow_recovery(self.db_path, api_key="test", llm=fake, max_applications=5, limit=10)
        self.assertEqual(report["unmapped"], 1)
        # Second run: no candidates remain (both marked processed).
        report2 = run_workflow_recovery(self.db_path, api_key="test", llm=fake, max_applications=5, limit=10)
        self.assertEqual(report2["candidates"], 0)
        engine = create_engine(f"sqlite:///{self.db_path}")
        Session = sessionmaker(bind=engine)
        s = Session()
        r2 = s.get(InterventionRecord, "r2")
        self.assertEqual(r2.workflow_normalized["source"], "llm_recovery_unmapped")
        s.close()


if __name__ == "__main__":
    unittest.main()
