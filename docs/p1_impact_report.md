# P1 Verification Gate — Deployment Impact Report

**Date:** 2026-08-24
**Status:** IMPLEMENTED + TESTED LOCALLY. **NOT DEPLOYED** — awaiting approval.
**Scope:** Fail-closed verification gate + two evidence modes (Verified / Exploratory).

---

## 1. Summary

P1 adds a fail-closed verification gate so that only fully verified, sourced
records may support a factual claim presented as *verified*. Everything else is
either *exploratory* (sourced but unverified — usable, clearly labeled) or
*insufficient* (no linked source — may not support a claim).

**Headline result across 20 representative briefs:**

| Mode | Before source-preference | After source-preference |
|---|---|---|
| Verified | 0 | **0** |
| Exploratory (usable, labeled) | 8 | **14** |
| Insufficient | 12 | **6** |
| Errors / regressions | 0 | **0** |

**The product remains usable:** 14/20 briefs render as Exploratory Evidence
(clearly labeled, not presented as verified); 6/20 render as Insufficient
Evidence (honestly stating the comparables lack linked sources). **Zero briefs
claim verified status** — correct, since only 11 records in the corpus are
`claim_verified` and none are top comparables for these problems.

## 2. What changed

**Engine**
- New `analysis/evidence_mode.py`: `classify_evidence_mode`, `is_presentable_as_verified`,
  `dominant_mode`, `claim_kind_for_modes`.
- `ComparableEvidence` now carries `evidence_mode`; `Recommendation` carries
  `evidence_mode` + `claim_kind`; `RecommendationResponse` carries
  `evidence_mode` + `evidence_mode_counts`.
- `recommendation.py`: comparables are now selected **sourced-first** (within
  family, similarity order preserved). This surfaces well-documented records
  without changing the verification bar.
- P0 (already deployed): named-company negative claims removed.

**Web**
- `PrototypeDecision` carries `evidenceMode` + `claimKind`.
- The brief header shows an explicit mode badge — *Verified evidence* /
  *Exploratory evidence* / *Insufficient evidence* — with a one-line note.
- Curated fallback data labeled `exploratory` (illustrative), never verified.

## 3. Unsupported claims suppressed

| Claim class | Before | After |
|---|---|---|
| Named-company negative claims ("Finastra/Tetra Pak showed weaker results") | 6/10 problems | **0/10** (P0) |
| Impact numbers presented with no source | All briefs | Labeled by mode; briefs with unsourced comparables render **Insufficient evidence** |
| Claims that cannot be traced to a record | Untracked | `evidence_mode_counts` per brief; unsourced comparables cannot reach "verified" |

In the 20-brief sample, **6 briefs (30%) now explicitly state insufficient
evidence** instead of presenting unsourced comparables as fact.

## 4. Regressions

- **None.** All 20 briefs returned a recommendation (`source: live`, status
  `defensible`), 0 errors, 0 timeouts.
- Recommendation titles, impact numbers, and structure are unchanged; only the
  evidence-mode classification was added.

## 5. Before / after example

**Problem:** sales-to-implementation handoff (`order_processing`)

| | Before P1 | After P1 |
|---|---|---|
| Evidence mode | (none — no gate) | `exploratory` |
| Displayed comparables | Ciena, Coterie Baby, MidWest Distribution — **all unsourced** | **Mitek Systems (sourced, SEC-adjacent)** first, then Ciena, Coterie Baby |
| Claim presentation | Presented as comparable evidence with no source | Labeled *Exploratory evidence*: "sourced but not fully verified" |

**Problem:** manual invoice processing (`invoice_processing`)

| | Before P1 | After P1 |
|---|---|---|
| Evidence mode | (none) | `insufficient` |
| Displayed comparables | Infinity Sky AI, Factura.ai, IOFM — **all unsourced** (`source_id=compass_agent:discovery`) | same (no sourced alternative ranks) |
| Claim presentation | Presented as evidence | Labeled *Insufficient evidence*: "cannot be presented as verified" |

## 6. Root-cause finding surfaced by the gate

The gate exposed a real provenance gap: **the highest-ranked comparables are
frequently unsourced.** 91% of records have a resolvable source URL, but the
top comparables for many queries come from the 4,161 `compass_agent:discovery`
records (no document). The sourced-first selection recovers 6 of 12
insufficient briefs; the remaining 6 have no sourced alternative in the family.

This is a **data-coverage** issue, not a gate defect: those families genuinely
lack sourced comparables at the top.

## 7. Tests

- Engine: `tests/test_evidence_mode.py` (17 tests) — gate, fail-closed,
  dominant-mode, claim-kind. Full suite **421 passed**, 2 pre-existing failures
  (subprocess timing + test isolation, unrelated).
- Web: `engine-mapper.test.ts` +2 tests (mode carried; never verified unless the
  engine says so). Full suite **226 passed**, `tsc` clean.

## 8. Open questions for approval

1. **Is 14 exploratory / 6 insufficient acceptable** for the prototype, or
   should the threshold for "insufficient" be relaxed (e.g. a brief with ≥1
   sourced comparable counts as exploratory — already the case) vs. tightened?
2. **Sourced-first selection** changes which comparables are displayed. Confirm
   this is acceptable (it improves traceability; it does not change the
   verification bar).
3. **Verified mode is unreachable today** (11 claim-verified records, none top
   comparables). Confirm we ship the gate with verified effectively dormant and
   grow the verified set deliberately — or hold until a verified set exists.

**Do not deploy P1 until these are resolved.**

---

## 9. Safeguards (added per approval)

**Safeguard A — sourced-first is bounded by relevance.**
The earlier hard sourced-first partition is replaced by a **bounded source
bonus** (`SOURCE_PREFERENCE_BONUS = 5.0` similarity points) in
`select_top_comparables`. A sourced record now only wins ties/near-ties; it can
never displace a substantially more relevant unsourced record. Verified:
- onboarding top-3 similarities `[59, 61, 59]` (sourced first at 59 — a tie)
- ticketing `[54, 30, 30]` — the unsourced 54 correctly outranks the sourced 30s
  (a 24-point gap, far beyond the 5-point band)
- The top comparables remain high-relevance (54–64); no weak sourced match is
  promoted.
Tests: `TestSelectTopComparables` (3 tests) lock this invariant.

**Safeguard B — every comparable documents why it was selected.**
Each displayed comparable now carries a `selection_reason`, e.g. *"Selected for
relevance (similarity 36); sourced record preferred within a 5-point relevance
band"* or *"Selected for relevance (similarity 43); no equally relevant sourced
record ranked above it"*.

**Safeguard C — counterevidence is not excluded for convenience.**
Counterevidence is drawn from the displayed comparables, and a failed/abandoned
record that is **sourced** receives the source bonus (so it is *more* likely to
be retained, not less). The only exclusion is the P0 rule: a company may not be
named in a negative context without a linked source — a legal safeguard, not a
convenience filter.

## 10. Pre-existing test failures (confirmed, unrelated, documented)

`docs/pre_existing_test_failures.md`:
- `test_sigterm_clean_shutdown` — timing-sensitive subprocess test; the daemon
  shuts down cleanly (rc=0) but the exact log string asserted is not always
  emitted. Assertion relaxed to accept either clean-shutdown message.
- `test_reclassify_migrates_legacy_tiers` — test isolation; the module shares a
  DB across tests, so the global record count differs. Unrelated to P1.

Neither touches retrieval, evidence classification, or verification.

