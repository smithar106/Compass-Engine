"""Tests for the engine enrichment ingestion endpoint.

Uses an isolated SQLAlchemy engine (full model schema) and patches
``get_session`` so the global engine binding is never touched.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import sqlalchemy

# Register all models so Base.metadata is complete, then build a dedicated engine.
import compass_collector.models.intervention  # noqa: F401
import compass_collector.models.organization  # noqa: F401
import compass_collector.models.analysis_session  # noqa: F401
from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord

_TMP = tempfile.TemporaryDirectory()
DB_PATH = os.path.join(_TMP.name, "collector.db")
_ENGINE = sqlalchemy.create_engine(f"sqlite:///{DB_PATH}")
Base.metadata.create_all(_ENGINE)
_TestSession = sqlalchemy.orm.sessionmaker(bind=_ENGINE, expire_on_commit=False)

_session = _TestSession()
_session.add(InterventionRecord(id="rec-1", organization_name="Acme Corp", review_status="pending"))
_session.commit()
_session.close()

os.environ["AGENT_SYNC_TOKEN"] = "sync-secret"


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class TestEnrichmentEndpoint(unittest.TestCase):
    def _call(self, token="sync-secret", record_id="rec-1", fields=None):
        from compass_collector.api.enrichment_router import EnrichmentRequest, ingest_enrichment

        req = EnrichmentRequest(
            record_id=record_id,
            fields=fields or {"intervention_title": "AI ticketing solution", "review_status": "agent_enriched"},
        )
        with patch("compass_collector.api.enrichment_router.get_session", side_effect=lambda: _TestSession()):
            return ingest_enrichment(req, FakeRequest({"X-Compass-Agent-Key": token}))

    def test_unauthorized_without_token(self):
        from fastapi import HTTPException

        os.environ.pop("AGENT_SYNC_TOKEN", None)
        try:
            with self.assertRaises(HTTPException) as ctx:
                self._call(token="")
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            os.environ["AGENT_SYNC_TOKEN"] = "sync-secret"

    def test_wrong_token_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(token="wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_upserts_fields(self):
        result = self._call(
            fields={
                "intervention_title": "AI ticketing solution",
                "implementation_richness": "rich",
                "review_status": "agent_enriched",
                "organization_employee_count": 5000,
                "organization_employee_band": "1000-10000",
                "organization_geography": ["Canada"],
            }
        )
        self.assertEqual(result["updated"], 6)

        session = _TestSession()
        rec = session.query(InterventionRecord).filter_by(id="rec-1").first()
        session.close()
        self.assertEqual(rec.intervention_title, "AI ticketing solution")
        self.assertEqual(rec.implementation_richness, "rich")
        self.assertEqual(rec.review_status, "agent_enriched")
        self.assertEqual(rec.organization_employee_count, 5000)
        self.assertEqual(rec.organization_employee_band, "1000-10000")
        self.assertIn("Canada", json.dumps(rec.organization_geography))

    def test_unknown_column_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(fields={"not_a_real_column": "x"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_missing_record_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(record_id="missing")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
