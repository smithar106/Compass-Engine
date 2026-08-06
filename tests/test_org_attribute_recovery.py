"""Tests for the Org Attribute Recovery Worker.

Covers: candidate selection (missing geo/size), LLM payload → organization
_normalized mapping (incl. employee band derivation), writes, dry-run, and
no-key skip. Temp-file DB + injected fake LLM — no network.
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

from compass_agent.org_attribute_recovery import (
    _candidate,
    _map_recovered,
    run_org_attribute_recovery,
)


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, text, system, user, title, url):
        self.calls += 1
        resp = self._responses.pop(0) if self._responses else {"geography": None, "employee_count": None}
        return NS(payload=resp, cost=0.0002)


def _make_db(records):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from compass_collector.models.document import Document

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    for r in records:
        s.add(InterventionRecord(**r))
    body = "This document describes the implementation in detail. " * 30
    s.add(Document(id="d1", url="https://example.com/1", cleaned_text=body + "headquartered in Germany"))
    s.commit()
    s.close()
    return path


def _records():
    return [
        dict(id="r1", organization_name="Acme GmbH", intervention_title="Invoice automation",
             problem_statement="", problem_business_function=["finance"], document_id="d1",
             organization_normalized={"primary_industry": {"value": "financial_services", "confidence": 1.0}}),
        dict(id="r2", organization_name="Beta", intervention_title="Call center automation",
             problem_statement="", problem_business_function=["operations"], document_id="d1",
             organization_normalized={"geography": {"value": "United States", "confidence": 1.0},
                                      "employee_count": {"value": "500", "confidence": 1.0}}),
    ]


class TestCandidate(unittest.TestCase):
    def test_missing_attrs_is_candidate(self):
        self.assertTrue(_candidate(NS(organization_normalized={"primary_industry": {}})))
        self.assertTrue(_candidate(NS(organization_normalized={})))
        self.assertTrue(_candidate(NS(organization_normalized=None)))

    def test_known_attrs_not_candidate(self):
        rec = NS(organization_normalized={
            "geography": {"value": "United States", "confidence": 1.0},
            "employee_count": {"value": "500", "confidence": 1.0},
        })
        self.assertFalse(_candidate(rec))


class TestMapping(unittest.TestCase):
    def test_geography_and_employee(self):
        entries = _map_recovered({"geography": "Germany", "employee_count": "12,500"})
        self.assertEqual(entries["geography"]["value"], "Germany")
        self.assertEqual(entries["geography"]["source"], "llm_recovery")
        self.assertEqual(entries["employee_count"]["value"], "12500")
        self.assertIn("employee_band", entries)  # band derived

    def test_nulls_ignored(self):
        self.assertEqual(_map_recovered({"geography": None, "employee_count": None}), {})

    def test_invalid_employee_ignored(self):
        entries = _map_recovered({"geography": "UK", "employee_count": "many"})
        self.assertNotIn("employee_count", entries)
        self.assertIn("geography", entries)


class TestWorkerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db(_records())

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_recovery_and_write(self):
        fake = _FakeLLM([{"geography": "Germany", "employee_count": 1200}])
        report = run_org_attribute_recovery(
            self.db_path, api_key="test", llm=fake, max_applications=5, limit=10
        )
        self.assertEqual(report["candidates"], 1)  # r2 skipped (known)
        self.assertEqual(report["applied"], 1)
        self.assertEqual(report["geography_recovered"], 1)
        self.assertEqual(report["employee_count_recovered"], 1)
        engine = create_engine(f"sqlite:///{self.db_path}")
        Session = sessionmaker(bind=engine)
        s = Session()
        r1 = s.get(InterventionRecord, "r1")
        norm = r1.organization_normalized
        self.assertEqual(norm["geography"]["value"], "Germany")
        self.assertEqual(norm["employee_count"]["value"], "1200")
        self.assertEqual(norm["employee_band"]["value"], "1000-10000")
        s.close()

    def test_dry_run_calls_nothing(self):
        report = run_org_attribute_recovery(self.db_path, api_key="", dry_run=True, max_applications=5, limit=10)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["applied"], 0)

    def test_no_api_key_skips(self):
        report = run_org_attribute_recovery(self.db_path, api_key="", max_applications=5, limit=10)
        self.assertEqual(report["skipped"], "no_api_key")


if __name__ == "__main__":
    unittest.main()
