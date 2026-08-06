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
import compass_collector.models.outcome  # noqa: F401
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

    def test_metrics_upsert_idempotent(self):
        """Promotion upserts MetricRecords keyed to the promote source and is
        idempotent across repeated apply runs."""
        from compass_collector.api.enrichment_router import EnrichmentRequest, ingest_enrichment
        from compass_collector.models.intervention import MetricRecord

        session = _TestSession()
        session.add(InterventionRecord(id="rec-m", organization_name="Beta Industries", review_status="pending"))
        session.commit()
        session.close()

        metrics = [{"metric_name": "handle_time", "category": "efficiency", "percentage_change": -30}]
        for _ in range(2):
            req = EnrichmentRequest(record_id="rec-m", source="compass_agent:promote", metrics=metrics)
            with patch("compass_collector.api.enrichment_router.get_session", side_effect=lambda: _TestSession()):
                ingest_enrichment(req, FakeRequest({"X-Compass-Agent-Key": "sync-secret"}))
        session = _TestSession()
        rows = session.query(MetricRecord).filter(MetricRecord.intervention_id == "rec-m").all()
        session.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].percentage_change, -30)
        self.assertEqual(rows[0].source_id, "compass_agent:promote")

    def test_reclassify_promotes_to_gold(self):
        """Promotion fills the gold-card gaps and the engine reclassifies the
        stored evidence_level from the resulting state."""
        from compass_collector.api.enrichment_router import EnrichmentRequest, ingest_enrichment
        from compass_collector.models.intervention import InterventionRecord

        session = _TestSession()
        session.add(InterventionRecord(id="rec-g", organization_name="Gamma Electric", review_status="pending"))
        session.commit()
        session.close()

        req = EnrichmentRequest(
            record_id="rec-g",
            source="compass_agent:promote",
            fields={
                "has_baseline": True,
                "problem_baseline_description": "Manual process, 40 tickets/day",
                "intervention_measurement_period_value": 6,
                "intervention_measurement_period_unit": "months",
                "sample_size": 120,
                "independently_verified": True,
            },
            metrics=[{"metric_name": "cost", "category": "finance", "percentage_change": -40}],
            reclassify=True,
        )
        with patch("compass_collector.api.enrichment_router.get_session", side_effect=lambda: _TestSession()):
            result = ingest_enrichment(req, FakeRequest({"X-Compass-Agent-Key": "sync-secret"}))
        self.assertEqual(result["evidence_level"], "gold")

        session = _TestSession()
        rec = session.query(InterventionRecord).filter_by(id="rec-g").first()
        session.close()
        self.assertEqual(rec.evidence_level, "gold")

    def test_missing_record_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(record_id="missing")
        self.assertEqual(ctx.exception.status_code, 404)


class TestIngestEndpoint(unittest.TestCase):
    def _ingest(self, req, token="sync-secret"):
        from compass_collector.api.enrichment_router import IngestRequest, ingest_evidence

        with patch("compass_collector.api.enrichment_router.get_session", side_effect=lambda: _TestSession()):
            return ingest_evidence(req, FakeRequest({"X-Compass-Agent-Key": token}))

    def _req(self, org="Acme Ingest", title="AI onboarding automation", tier="silver", depth=2):
        from compass_collector.api.enrichment_router import IngestRequest

        return IngestRequest(
            organization_name=org,
            intervention_title=title,
            workflow="onboarding",
            evidence_tier=tier,
            organization_industry=["technology"],
            implementation_fields={
                "rollout_strategy": "Pilot in one team, then phased rollout",
                "success_criteria": ["onboarding time < 5 days"],
                "lessons_learned": ["train champions early"],
                "implementation_pattern": ["Pilot -> Department Rollout"],
            } if depth >= 2 else {"rollout_strategy": "x"} if depth == 1 else {},
            outcomes=[{"metric_name": "onboarding_time", "category": "time", "percentage_change": -60}],
        )

    def test_accepts_rich_record(self):
        result = self._ingest(self._req())
        self.assertTrue(result["accepted"])
        self.assertTrue(result["rich"])
        self.assertTrue(result["record_id"])
        session = _TestSession()
        rec = session.query(InterventionRecord).filter_by(id=result["record_id"]).first()
        session.close()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.evidence_level, "silver")
        self.assertEqual(rec.organization_name, "Acme Ingest")

    def test_duplicate_rejected(self):
        self._ingest(self._req())
        result = self._ingest(self._req())
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "duplicate_org_title")

    def test_invalid_tier_rejected(self):
        from compass_collector.api.enrichment_router import IngestRequest

        result = self._ingest(IngestRequest(
            organization_name="X", intervention_title="T", workflow="w",
            evidence_tier="rejected",
        ))
        self.assertFalse(result["accepted"])
        self.assertIn("invalid_evidence_tier", result["reason"])

    def test_missing_required_rejected(self):
        from compass_collector.api.enrichment_router import IngestRequest

        result = self._ingest(IngestRequest(
            organization_name="", intervention_title="T", workflow="w", evidence_tier="silver"
        ))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "missing_required_fields")

    def test_insufficient_depth_rejected(self):
        result = self._ingest(self._req(org="Acme Shallow", tier="bronze", depth=0))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "insufficient_depth")

    def test_unauthorized(self):
        from compass_collector.api.enrichment_router import IngestRequest
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._ingest(self._req(), token="")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()


class TestOutcomeEndpoint(unittest.TestCase):
    def test_record_and_list_outcome(self):
        from compass_collector.api.outcome_router import OutcomeRequest, record_outcome, list_outcomes

        with patch("compass_collector.api.outcome_router.get_session", side_effect=lambda: _TestSession()):
            result = record_outcome(OutcomeRequest(
                recommendation_id="rec-1",
                organization_name="Acme",
                accepted=True,
                implemented_intervention="AI ticketing",
                blueprint_followed=True,
                realized_cost=120000.0,
                would_recommend_same=True,
            ))
            self.assertEqual(result["status"], "recorded")

        with patch("compass_collector.api.outcome_router.get_session", side_effect=lambda: _TestSession()):
            listing = list_outcomes(limit=10)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["outcomes"][0]["organization_name"], "Acme")
        self.assertEqual(listing["outcomes"][0]["realized_cost"], 120000.0)

    def test_missing_recommendation_rejected(self):
        from compass_collector.api.outcome_router import OutcomeRequest, record_outcome
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            record_outcome(OutcomeRequest(recommendation_id=""))
        self.assertEqual(ctx.exception.status_code, 400)
