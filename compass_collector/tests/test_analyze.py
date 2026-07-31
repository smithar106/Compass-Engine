"""Tests for the Analyze pathway: shared modules + server-side session endpoints."""
import os
import tempfile

os.environ["COLLECTOR_DATABASE_URL"] = "sqlite:///" + tempfile.mkdtemp() + "/analyze_test.db"

from compass_collector.database import Base, engine  # noqa: E402
from compass_collector.models.analysis_session import AnalysisSession  # noqa: E402,F401
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord  # noqa: E402,F401
from compass_collector.models.document import Document  # noqa: E402,F401
from compass_collector.models.source import SourceRegistry  # noqa: E402,F401
from compass_collector.models.walkthrough import (  # noqa: E402,F401
    ImplementationPlan,
    ImplementationRequest,
    SavedDecision,
)

Base.metadata.create_all(bind=engine)

from compass_collector.analysis.analyze import (  # noqa: E402
    normalize_problem,
    infer_desired_outcome,
    select_follow_ups,
    infer_answers_from_text,
    build_profile_from_analyze,
)
from compass_collector.api import analyze_router as ar  # noqa: E402


def canned_decision(confidence="moderate", tier="silver", comparables=3, title="Workflow Automation"):
    return {
        "recommendation_id": "abc",
        "recommendations": [
            {
                "title": title,
                "confidence": {"score": 0.65, "label": confidence, "explanation": ""},
                "evidence_summary": {
                    "overall_tier": tier,
                    "total_comparables": comparables,
                    "gold_count": 0,
                    "silver_count": comparables,
                    "bronze_count": 0,
                },
                "information_gaps": [{"title": "Annual workflow volume and handling time", "explanation": "", "effect_on_confidence": ""}],
                "comparable_implementations": [{"record_id": "rec-1", "organization": "OrgA", "evidence_tier": "silver"}],
                "outcome_ranges": [],
                "risks": [],
                "alternatives_considered": [],
                "assumptions_detail": [],
                "next_validation_step": {"action": "Measure baseline"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Shared module tests (parity with the web client's lib)
# ---------------------------------------------------------------------------


def test_normalize_invoice():
    n = normalize_problem("Manual invoice processing is expensive and slow; matching errors")
    assert n["workflow"] == "invoice_processing"
    assert n["businessFunction"] == "finance"
    assert n["desiredOutcome"] == "cost"
    assert len(n["rootCauseHypothesis"]) > 20


def test_normalize_onboarding_time():
    n = normalize_problem("Customer onboarding takes 45 days because approvals and setup are manual")
    assert n["workflow"] == "onboarding"
    assert n["desiredOutcome"] == "time"


def test_normalize_obscure_defaults():
    n = normalize_problem("Quantum chemistry solvent optimization in semiconductor cleanrooms")
    assert n["workflow"]  # non-empty default
    assert n["decision"]


def test_select_followups_limited_to_five():
    qs = select_follow_ups("Manual invoice processing is expensive", {}, [{"title": "Annual workflow volume and handling time"}], 5)
    assert 0 < len(qs) <= 5


def test_select_followups_skips_inferred_and_answered():
    qs = select_follow_ups(
        "Onboarding takes 45 days for 20 people, daily volume, with many exceptions",
        {"exception_rate": "Many (10-30%)"},
        [],
        5,
    )
    ids = [q["id"] for q in qs]
    assert "cycle_time" not in ids
    assert "workflow_frequency" not in ids
    assert "people_involved" not in ids
    assert "exception_rate" not in ids


def test_select_followups_promotes_labor_gap():
    qs = select_follow_ups("Manual invoice processing is expensive", {}, [{"title": "Loaded labor cost"}], 5)
    assert "labor_cost" in [q["id"] for q in qs]


def test_select_followups_no_duplicates_with_overlapping_gaps():
    qs = select_follow_ups(
        "Manual invoice processing is expensive",
        {},
        [{"title": "Annual workflow volume and handling time"}, {"title": "Loaded labor cost"}],
        5,
    )
    ids = [q["id"] for q in qs]
    assert len(set(ids)) == len(ids)


def test_select_followups_deterministic():
    qs_a = select_follow_ups("Manual invoice processing is expensive", {"cycle_time": "Hours"}, [{"title": "Annual workflow volume"}], 5)
    qs_b = select_follow_ups("Manual invoice processing is expensive", {"cycle_time": "Hours"}, [{"title": "Annual workflow volume"}], 5)
    assert [q["id"] for q in qs_a] == [q["id"] for q in qs_b]


def test_infer_answers():
    inferred = infer_answers_from_text("Takes 45 days, runs daily, 20 people, many exceptions, budget $50K")
    assert {"cycle_time", "workflow_frequency", "people_involved", "exception_rate", "budget_range"}.issubset(inferred)


def test_build_profile():
    n = normalize_problem("Manual invoice processing is expensive")
    p = build_profile_from_analyze(n, {"cycle_time": "Hours", "workflow_frequency": "Daily"})
    assert p["business_function"] == "finance"
    assert p["workflow"] == "invoice_processing"
    assert p["workflow_frequency"] == "Daily"
    assert p["desired_outcome"] == "cost"


# ---------------------------------------------------------------------------
# Server-side session endpoint tests
# ---------------------------------------------------------------------------


def test_create_analysis(monkeypatch):
    monkeypatch.setattr(ar, "_run_engine", lambda norm, ans: canned_decision())
    out = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    assert out["analysis_id"]
    assert out["normalization"]["workflow"] == "invoice_processing"
    assert len(out["questions"]) <= 5
    assert out["engine_version"] == "3.1.0"


def test_confirm_and_answers_and_restore(monkeypatch):
    calls = {"n": 0}

    def fake(norm, ans):
        calls["n"] += 1
        return canned_decision()

    monkeypatch.setattr(ar, "_run_engine", fake)
    created = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    aid = created["analysis_id"]

    confirmed = ar.confirm_analysis(aid, ar.ConfirmRequest(edits={"desiredOutcome": "cost"}))
    assert confirmed["normalization"]["desiredOutcome"] == "cost"

    answered = ar.submit_answers(aid, ar.AnswersRequest(answers={"cycle_time": "Hours", "workflow_frequency": "Daily"}))
    assert answered["answers"]["cycle_time"] == "Hours"

    restored = ar.get_analysis(aid)
    assert restored["answers"]["workflow_frequency"] == "Daily"
    assert restored["evidence_ids"] == ["rec-1"]
    assert calls["n"] >= 3


def test_insufficient_evidence_status(monkeypatch):
    def fake(norm, ans):
        return canned_decision(confidence="insufficient", tier="insufficient", comparables=0)

    monkeypatch.setattr(ar, "_run_engine", fake)
    created = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Quantum chemistry solvent optimization"))
    # context gathering first
    assert created["status"] == "awaiting_answers"
    answered = ar.submit_answers(created["analysis_id"], ar.AnswersRequest(answers={"cycle_time": "Hours"}))
    assert answered["status"] == "insufficient_evidence"


def test_determinism_across_sessions(monkeypatch):
    monkeypatch.setattr(ar, "_run_engine", lambda norm, ans: canned_decision())
    a = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    b = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    assert a["normalization"] == b["normalization"]
    assert [q["id"] for q in a["questions"]] == [q["id"] for q in b["questions"]]


def test_answers_materially_change_context(monkeypatch):
    """Clarification answers must be recorded and reach the engine profile."""
    captured = []

    def fake(norm, ans):
        captured.append(dict(ans))
        return canned_decision()

    monkeypatch.setattr(ar, "_run_engine", fake)
    created = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    aid = created["analysis_id"]
    ar.submit_answers(aid, ar.AnswersRequest(answers={"workflow_frequency": "Daily", "exception_rate": "Many (10-30%)"}))
    assert captured[-1].get("workflow_frequency") == "Daily"
    assert captured[-1].get("exception_rate") == "Many (10-30%)"


def test_answers_produce_materially_different_context_a_vs_b(monkeypatch):
    """Two materially different contexts must reach the engine as different profiles
    and be recorded in the session — the A/B contrast the product depends on.
    (Current engine ranking does not yet consume these fields; that is a P1 scoring
    item. The session must still record and re-run with the enriched context.)"""

    def fake(norm, ans):
        return canned_decision(confidence="moderate", tier="silver", comparables=3)

    monkeypatch.setattr(ar, "_run_engine", fake)

    a = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    b = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))

    ar.submit_answers(
        a["analysis_id"],
        ar.AnswersRequest(
            answers={
                "workflow_frequency": "Monthly",
                "cycle_time": "Weeks",
                "exception_rate": "Highly variable (30%+)",
                "judgment_requirement": "Mostly judgment",
            }
        ),
    )
    ar.submit_answers(
        b["analysis_id"],
        ar.AnswersRequest(
            answers={
                "workflow_frequency": "Daily",
                "cycle_time": "Minutes",
                "exception_rate": "Few (<5%)",
                "judgment_requirement": "Fully rule-based",
            }
        ),
    )

    ra = ar.get_analysis(a["analysis_id"])
    rb = ar.get_analysis(b["analysis_id"])
    assert ra["answers"]["workflow_frequency"] == "Monthly"
    assert rb["answers"]["workflow_frequency"] == "Daily"
    assert ra["answers"]["judgment_requirement"] != rb["answers"]["judgment_requirement"]
    assert len(ra["retrieval_snapshots"]) >= 2
    assert ra["status"] == "decision_ready"


def test_walkthrough_implement_request_invite(monkeypatch):
    from compass_collector.api import walkthrough_router as wr

    def fake(norm, ans):
        return canned_decision(confidence="moderate", tier="silver", comparables=3)

    monkeypatch.setattr(ar, "_run_engine", fake)
    created = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive"))
    aid = created["analysis_id"]

    # Implement This Plan → six ordered stages
    plan = wr.create_implementation(aid, wr.ImplementRequest(path="partner", partner_id="demo-northstar"))
    assert plan["selected_path"] == "partner"
    assert len(plan["stages"]) == 6
    assert [s["index"] for s in plan["stages"]] == [1, 2, 3, 4, 5, 6]
    assert plan["partner_status"] == "not_requested"

    # Partner request → record + notification attempt + invite
    req = wr.request_partner(
        plan["implementation_id"],
        wr.PartnerRequestModel(
            partner_id="demo-northstar",
            contact_name="Jane",
            contact_email="jane@acme.com",
            organization="Acme",
            requested_timeline="8 weeks",
            notes="",
            consent=True,
        ),
    )
    assert req["status"] in ("submitted", "notification_sent")
    assert req["notification"]["partner"]["status"] in ("dev_fallback", "sent", "failed")
    assert req["notification"]["user"]["status"] in ("dev_fallback", "sent", "failed")

    # Partner secure invite view + accept
    invite = wr.partner_invite_view(plan["implementation_id"], plan["invite_token"])
    assert invite["partner_name"] == "Northstar Automation"
    assert len(invite["stages"]) == 6
    accepted = wr.partner_invite_accept(plan["implementation_id"], plan["invite_token"])
    assert accepted["partner_status"] == "accepted"

    # Save decision → permanent link
    saved = wr.save_decision(aid, wr.SaveDecisionModel(email=""))
    assert saved["permalink"].endswith(aid)


def test_metadata_schema():
    from compass_collector.api.app import get_metadata

    m = get_metadata()
    for key in [
        "published_records",
        "unique_organizations",
        "industries",
        "measured_outcomes",
        "decision_questions",
        "gold",
        "silver",
        "bronze",
        "last_published_at",
        "engine_version",
    ]:
        assert key in m
    assert m["decision_questions"] == 8


def test_session_restores_complete_state(monkeypatch):
    def fake(norm, ans):
        return canned_decision()

    monkeypatch.setattr(ar, "_run_engine", fake)
    created = ar.create_analysis(ar.AnalyzeCreateRequest(problem_text="Manual invoice processing is expensive", attachments=["pasted policy text"]))
    aid = created["analysis_id"]
    ar.confirm_analysis(aid, ar.ConfirmRequest(edits={"desiredOutcome": "time"}))
    restored = ar.get_analysis(aid)
    assert restored["attachments"] == ["pasted policy text"]
    assert restored["edits"]["desiredOutcome"] == "time"
    assert restored["inferred"]
    assert restored["decision"] is not None
    assert restored["retrieval_snapshots"]
    assert restored["scoring_version"]
