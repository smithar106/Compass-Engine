# Verified Brief → Production Engine — Implementation Plan (Phases 2–4)

**Date:** 2026-08-24
**Status:** PLAN ONLY — not implemented, not deployed. Awaiting approval.
**Predecessor:** Phase 1 comparability audit (`Compass-Web/docs/verified-brief-comparability-audit.md`)
— finding: 0 direct implementation, 5 indirect contextual, 2 not relevant.

**Objective:** Compass must generate defensible decision briefs through its
production engine, not merely display one curated example.

---

## Current state (what exists)

- **Engine** already has: `verification_status` (source dimension), `publication_status`,
  `ComparableEvidence.source_url/source_title/supporting_passage`,
  `OutcomeRange.source_record_ids/calculation_method/sample_size`, and the P1
  `evidence_mode` gate.
- **Web** has: a curated verified set (`src/data/prototype/verified-invoice.ts`)
  with a **separate** comparability field, rendered by `/verified-brief`; and the
  live prototype briefs consuming engine output.
- **Gap:** the verified set lives only in the web; the engine cannot produce it;
  comparability is not modeled in the engine.

---

## Phase 2 — Production engine integration

**Goal:** one canonical evidence source; the engine generates the verified brief.

### 2.1 Model comparability in the engine (separate from verification)

Add a comparability dimension to `ComparableEvidence` (never overwriting
`verification_status`):

```
comparability: "direct_implementation" | "indirect_contextual" | "not_relevant"
documents_implementation: bool
establishes_intervention_outcome: bool
comparability_reason: str
```

- New module `analysis/comparability.py` (naming TBD; distinct from the existing
  `comparability.py` — verify no collision) with
  `classify_comparability(record, intervention_family, metrics) -> Comparability`.
- Deterministic rules (no LLM): a record is `direct_implementation` only if its
  intervention matches the recommended family **and** a metric in the source is
  attributable to that intervention; otherwise `indirect_contextual` or
  `not_relevant`.
- **Default is `not_relevant`/`indirect_contextual`** — fail-closed, never
  auto-promote to direct.

### 2.2 One canonical evidence source

- Move the curated verified set into the engine as data
  (`compass_collector/data/verified/<category>.json`) or, preferably, derive it
  from `intervention_records` where `verification_status = claim_verified` +
  a `comparability` classification.
- **Decision needed:** curated JSON file vs. DB-backed. Recommend DB-backed once
  the verified set grows; a small curated file is acceptable for the first
  category, exposed via the engine API.
- New endpoint: `GET /api/evidence/verified?workflow=<slug>` returning the
  verified set with source + comparability + passages. The web deletes its
  hardcoded `verified-invoice.ts` and fetches this.

### 2.3 Preserve existing behavior

- `evidence_mode` (P1) unchanged; exploratory/insufficient modes remain.
- Recommendation outputs already retain `source_record_ids` (in `OutcomeRange`);
  extend to `ComparableEvidence.record_id` (already present).
- No new verification logic — reuse `evidence_mode.py` + `strict-verify` semantics.

**Smallest first step:** expose the existing curated set via the engine endpoint
(no DB migration), and have the web fetch it. Then migrate to DB-backed.

---

## Phase 3 — Citation & calculation UI (production briefs)

Extend the existing `EvidenceCard` + `OutcomeRange` rendering to the live
prototype briefs.

Expose per evidence-derived claim:
- source title + direct URL
- supporting passage
- verification status (source dimension)
- comparability classification (relevance dimension)
- source record ID
- calculation methodology
- sample size (where available)
- assumptions / limitations

**Hard rule:** never display a source citation as proof of an outcome the source
does not establish. If `comparability != direct_implementation`, the citation
renders with an explicit "context only — does not establish this outcome" label.

Reuse the `/verified-brief` layout as the target design; generalize the
component so both the verified brief and live briefs share it.

---

## Phase 4 — Testing & acceptance

Automated tests:
1. **Source verification vs comparability** — independent fields; one never
   implies the other.
2. **Unsupported causal attribution** — a record that is `indirect_contextual`
   or `not_relevant` can never render as evidence of the intervention's outcome.
3. **Reproducible evidence selection** — same inputs → same comparables
   (deterministic).
4. **Missing source handling** — no source → no citation; claim labeled
   illustrative/omitted.
5. **Claim-to-source traceability** — every evidence-derived number resolves to a
   record id + source URL.
6. **Engine ↔ UI consistency** — the brief renders exactly what the engine
   returns (no web-side re-derivation).

Then run representative problems and compare before/after.

---

## Migration risks

| Risk | Detail | Mitigation |
|---|---|---|
| **Comparability naming collision** | `analysis/comparability.py` may already exist | Inspect first; use a distinct module name (e.g. `evidence_comparability.py`) |
| **Auto-promotion** | A classifier could wrongly mark a record `direct_implementation` | Fail-closed default; require intervention-family match + attributable metric; never auto-promote from `supporting` |
| **Duplicate verification logic** | Re-deriving verification in the engine | Reuse `evidence_mode.py`; single source of truth |
| **Thin verified set** | Only 11 claim-verified records; likely 0 direct comparables | Ship the honest "no direct implementation evidence" state (already the Phase-1 outcome); grow deliberately |
| **DB migration** | New `comparability` column | Additive, nullable, default `not_relevant`; no backfill that fabricates |
| **Web/engine divergence** | Web keeps a hardcoded copy | Delete `verified-invoice.ts` after the engine endpoint is live; add an engine-UI consistency test |
| **Scope creep** | Turning this into a big refactor | Ship Phase 2 as: engine endpoint for the existing curated set → web fetches it. Defer DB-backed migration |

---

## Acceptance criteria

**Phase 2**
- [ ] One canonical evidence source (no hardcoded web dataset).
- [ ] Engine endpoint returns the verified set with source + comparability + passages.
- [ ] `evidence_mode` and exploratory/insufficient modes still work.
- [ ] Comparability and verification are separate fields everywhere.
- [ ] No new verification logic introduced.

**Phase 3**
- [ ] Every evidence-derived claim in a live brief shows source, verification,
      comparability, record id, method, sample size.
- [ ] A non-direct record never renders as proof of an outcome.

**Phase 4**
- [ ] All six test classes pass in CI.
- [ ] Representative problems produce consistent, reproducible output before/after.
- [ ] Engine output and UI agree exactly.

**Milestone (per Arthur)**
- [ ] One real customer decision processed end-to-end through the production
      engine, with traceable evidence and decision-maker feedback.

---

## Explicitly out of scope

- Expanding the evidence library (deferred per instruction).
- New product features / website redesign.
- Auto-promoting records to verified or direct.
- Deploying Phase 2–4 before approval.
