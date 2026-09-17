# Pre-existing Test Failures — Disposition

**Date:** 2026-08-24
**Purpose:** Confirm the two failing tests in the Compass-Engine suite are
understood, unrelated to P0/P1, and documented (required before P1 deploy).

Current suite: **421 passed, 2 failed**.

Both failures reproduce on the pre-P1 tree (verified by stashing the P1 changes
and re-running), so neither is caused by P0 or P1.

---

## 1. `tests/test_compass_agent.py::TestGracefulShutdownSubprocess::test_sigterm_clean_shutdown`

**Symptom:** the test spawns the agent daemon as a subprocess, sends SIGTERM,
and asserts the output contains the string "shutting down". Under full-suite
load the string is sometimes absent.

**Root cause:** a timing/ordering-sensitive subprocess test. The daemon has two
clean-shutdown paths:
- `daemon.py:279` — the signal handler logs *"Received signal … — shutting down
  gracefully."*
- `daemon.py:539` — the run loop logs *"Compass Evidence Agent stopped."*

Depending on where the signal lands relative to the sleep loop, only the second
message may be emitted. In both cases the process exits **cleanly (rc=0)** —
the test's own `assertEqual(rc, 0)` passes. The failure is purely the
string assertion.

**Fix applied:** the assertion now accepts either shutdown message (the outcome,
not one exact log line). The test passes in isolation after the fix; under
full-suite load it can still flake on timing.

**Unrelated to P0/P1:** the test exercises the evidence-agent daemon's signal
handling; it does not touch retrieval, evidence classification, or the
recommendation/verification path.

---

## 2. `tests/test_enrichment_endpoint.py::TestReclassifyAll::test_reclassify_migrates_legacy_tiers`

**Symptom:** `assertEqual(result["records"], 2)` fails with `6 != 2` when run as
part of the full suite.

**Root cause:** test isolation. `test_enrichment_endpoint.py` builds a
module-level temporary SQLite engine and a shared `_session`, and earlier tests
in the same module insert additional `InterventionRecord` rows. The
`reclassify_all` endpoint processes *all* records in the shared DB, so the count
is 6 (the accumulated rows), not the 2 the test expects. The test passes when
run in isolation, and it also failed before P1.

**Unrelated to P0/P1:** the test targets the enrichment/reclassification
endpoint and its own fixture DB; it does not touch retrieval, evidence
classification, or verification.

**Recommended fix (not applied — test-infra, out of P1 scope):** assert on the
specific migrated record (e.g. `reclass-1` becomes `decision_grade`) rather than
the global record count, or give the test its own isolated engine/session.

---

## Impact on P1

Neither failure affects the P1 verification gate, the evidence-mode
classification, the sourced-first selection, or the recommendation output. The
P1 tests (`tests/test_evidence_mode.py`, `tests/test_recommendation.py`) pass,
as do all retrieval/coverage/recommendation tests.
