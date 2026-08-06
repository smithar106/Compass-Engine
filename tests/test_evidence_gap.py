"""Phase 2 tests for the Evidence Gap Engine v2.

Covers: coverage-level thresholds, diversity/concentration detection,
gap scoring, shopping-list composition (search terms, library priority,
targets), sparse-dimension handling, the demand-weighted Decision Coverage
KPI, and end-to-end engine determinism on an in-memory graph.
"""

from __future__ import annotations

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compass_collector.database import Base
from compass_collector.models.intervention import InterventionRecord

from compass_agent.evidence_gap import (
    ENGINE_VERSION,
    compose_search_terms,
    coverage_level,
    diversity_stats,
    run_gap_engine,
    score_libraries,
)
from compass_agent.libraries import LIBRARY_REGISTRY


def _rec(
    wid,
    fn="finance",
    tier="decision_grade",
    workflow="invoice processing",
    vendors=None,
    software=None,
    industry="financial_services",
    geo=None,
    emp=None,
    rollout="yes",
):
    """Build an InterventionRecord-like object (SimpleNamespace) for helpers,
    or a real model row where indicated."""
    vendors_norm = {}
    for v in vendors or []:
        vendors_norm[v] = {"value": v, "confidence": 1.0}
    software_norm = {}
    for s in software or []:
        software_norm[s] = {"value": s, "confidence": 1.0, "family": "rpa" if "uipath" in s else "genai"}
    org_norm = {}
    if industry:
        org_norm["primary_industry"] = {"value": industry, "confidence": 1.0}
    if geo:
        org_norm["geography"] = {"value": geo, "confidence": 1.0}
    if emp:
        org_norm["employee_count"] = {"value": str(emp), "confidence": 1.0}
    from types import SimpleNamespace as NS

    return NS(
        id=wid,
        problem_business_function=[fn],
        intervention_components={"workflow": workflow},
        review_status=tier,
        evidence_level="",
        organization_normalized=org_norm,
        intervention_vendors_normalized=vendors_norm or None,
        intervention_software_normalized=software_norm or None,
        rollout_strategy=rollout or "",
        success_criteria="criteria" if rollout else "",
        lessons_learned="lessons" if rollout else "",
        implementation_pattern="pattern" if rollout else "",
        intervention_title="title",
        organization_name="org",
        has_baseline=rollout is not None,
    )


class TestCoverageLevel(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(coverage_level(0, 0.0), "absent")
        self.assertEqual(coverage_level(3, 0.5), "good")   # router: ratio >= 0.5 → good
        self.assertEqual(coverage_level(5, 0.15), "developing")
        self.assertEqual(coverage_level(12, 0.6), "good")
        self.assertEqual(coverage_level(30, 0.3), "excellent")
        self.assertEqual(coverage_level(10, 0.4), "good")


class TestDiversityStats(unittest.TestCase):
    def test_concentration_detected(self):
        recs = [_rec(f"r{i}", vendors=["uipath"] * 1 + ["oracle"], software=["uipath"]) for i in range(5)]
        # 5 records, 4 vendored, 3 uipath 1 oracle → share 0.75 → concentration
        recs = [_rec(f"r{i}", vendors=["uipath"], software=[]) for i in range(4)]
        recs += [_rec("r5", vendors=["oracle"], software=[])]
        d = diversity_stats(recs)
        self.assertTrue(d["concentration"])
        self.assertEqual(d["top_vendor"], "uipath")
        self.assertGreaterEqual(d["top_vendor_share"], 0.6)

    def test_diverse_not_concentrated(self):
        recs = [_rec(f"r{i}", vendors=[v]) for i, v in enumerate(["uipath", "oracle", "aws", "sap", "ibm"])]
        d = diversity_stats(recs)
        self.assertFalse(d["concentration"])
        self.assertEqual(d["vendors"], 5)

    def test_empty_category(self):
        d = diversity_stats([])
        self.assertEqual(d["vendors"], 0)
        self.assertIsNone(d["top_vendor"])
        self.assertFalse(d["concentration"])


class TestComposeSearchTerms(unittest.TestCase):
    def test_base_and_gold_terms(self):
        from compass_agent.evidence_gap import EvidenceNeed

        need = EvidenceNeed(
            workflow="invoice processing", business_function="finance",
            gold=0, decision_grade=0, missing_fields=["rollout_strategy"],
            diversity={"concentration": False}, target_industries=["healthcare"],
        )
        terms = compose_search_terms(need)
        self.assertIn("invoice processing finance implementation", terms)
        self.assertIn("invoice processing automation quantified results", terms)
        self.assertTrue(any("healthcare" in t for t in terms))

    def test_diversity_term_when_concentrated(self):
        from compass_agent.evidence_gap import EvidenceNeed

        need = EvidenceNeed(
            workflow="invoice processing", business_function="finance",
            diversity={"concentration": True, "top_vendor": "uipath", "present_vendors": ["uipath"]},
        )
        terms = compose_search_terms(need)
        self.assertTrue(any("uipath" not in t and "case study" in t for t in terms[1:3] or []) or
                        any(" OR " in t for t in terms))


class TestScoreLibraries(unittest.TestCase):
    def test_returns_priority_list(self):
        from compass_agent.evidence_gap import EvidenceNeed

        need = EvidenceNeed(workflow="invoice processing", business_function="finance")
        priority = score_libraries(need, LIBRARY_REGISTRY, top_n=3)
        self.assertEqual(len(priority), 3)
        self.assertTrue(all(isinstance(x, str) for x in priority))

    def test_fallback_when_no_hits(self):
        from compass_agent.evidence_gap import EvidenceNeed

        need = EvidenceNeed(workflow="zzz nonexistent workflow", business_function="zzz")
        priority = score_libraries(need, LIBRARY_REGISTRY, top_n=3)
        self.assertEqual(len(priority), 3)  # estimated-quality fallback


class TestEngineEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        Session = sessionmaker(bind=cls.engine)
        cls.session = Session()

        # Category A: healthy (15 records, good tier mix, diverse)
        for i in range(15):
            cls.session.add(InterventionRecord(
                id=f"a{i}", problem_business_function=["finance"],
                intervention_components={"workflow": "invoice processing"},
                review_status="decision_grade" if i % 3 else "gold",
                intervention_vendors_normalized={v: {"value": v, "confidence": 1.0}
                                                 for v in ("uipath", "oracle", "aws", "sap", "ibm")[i % 5:]},
                organization_normalized={"primary_industry": {"value": "financial_services", "confidence": 1.0}},
                rollout_strategy="x", success_criteria="x", lessons_learned="x", implementation_pattern="x",
            ))
        # Category B: weak (2 records, no gold, no decision-grade, concentrated)
        for i in range(2):
            cls.session.add(InterventionRecord(
                id=f"b{i}", problem_business_function=["legal"],
                intervention_components={"workflow": "contract review"},
                review_status="supporting",
                intervention_vendors_normalized={"uipath": {"value": "uipath", "confidence": 1.0}},
                organization_normalized={"primary_industry": {"value": "legal_services", "confidence": 1.0}},
                rollout_strategy="", success_criteria="", lessons_learned="", implementation_pattern="",
            ))
        cls.session.commit()

    def test_report_shape_and_ordering(self):
        report = run_gap_engine(session=self.session, top_n=10, min_impact=0.0)
        self.assertEqual(report.engine_version, ENGINE_VERSION)
        self.assertEqual(report.total_records, 17)
        self.assertEqual(report.categories, 2)
        # Weak category outranks healthy one by expected impact
        self.assertEqual(report.needs[0].workflow, "contract review")
        self.assertEqual(report.needs[0].decision_coverage, "absent")  # 0 high-quality
        self.assertEqual(report.needs[1].workflow, "invoice processing")
        self.assertEqual(report.needs[1].decision_coverage, "good")  # 15 HQ < 25 excellent

    def test_kpi_per_function(self):
        report = run_gap_engine(session=self.session)
        cov = report.decision_coverage_by_function
        self.assertIn("legal", cov)
        self.assertIn("finance", cov)
        self.assertGreater(cov["finance"]["coverage_pct"], cov["legal"]["coverage_pct"])

    def test_shopping_list_targets(self):
        report = run_gap_engine(session=self.session, top_n=5, min_impact=0.0)
        weak = report.shopping_list[0]
        self.assertGreater(weak.estimated_records_needed, 0)
        self.assertTrue(weak.target_industries)  # targets composed
        self.assertTrue(weak.search_terms)
        self.assertTrue(weak.source_library_priority)

    def test_deterministic(self):
        r1 = run_gap_engine(session=self.session)
        r2 = run_gap_engine(session=self.session)
        self.assertEqual([n.to_dict() for n in r1.needs], [n.to_dict() for n in r2.needs])


if __name__ == "__main__":
    unittest.main()
