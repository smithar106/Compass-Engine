# Plan B — Citation & Calculation UI for Production Briefs (for approval)

**Date:** 2026-08-24
**Status:** PLAN ONLY — no implementation.
**Goal:** expose provenance on the **live** Compass experience, not just the
special `/verified-brief` demonstration page.

---

## Objective

Every material claim in every production decision brief must be traceable to its
source and its limitations — with labels appropriate to what the evidence
actually supports.

## 1. What to expose (per evidence-derived claim)

| Field | Source |
|---|---|
| Source title + direct URL | `ComparableEvidence.source_title` / `source_url` |
| Supporting passage | `ComparableEvidence.supporting_passage` |
| Verification status (source dimension) | `verification_status` |
| Comparability (relevance dimension) | `comparability` (Plan A / Phase 2 model) |
| Outcome attribution | `outcome_attribution` |
| Source record ID | `record_id` |
| Calculation methodology | `OutcomeRange.calculation_method` |
| Sample size | `OutcomeRange.sample_size` |
| Assumptions / limitations | `attribution_limitation`, `limitations` |

## 2. Claim-type labels (the key requirement)

Each claim renders with a label matching what the evidence supports:

| Claim type | When | Rendering |
|---|---|---|
| **Verified finding** | `verification = claim_verified` AND `comparability = direct_implementation` AND `attribution = explicit` | Full citation; "verified finding" |
| **Exploratory hypothesis** | sourced but not verified/comparable | Citation + "exploratory — not verified"; no causal language |
| **Vendor-reported** | source is a vendor case study | "Vendor-reported" label; never "independently corroborated" |
| **Context only** | `indirect_contextual` / `not_relevant` | Citation shown as context; explicit "does not establish this outcome" |
| **Insufficient** | no source | No citation; claim labeled illustrative or omitted |
| **Assumption** | user-provided input | "Your assumption" |

**Hard rule:** never display a source citation as proof of an outcome the source
does not establish.

## 3. Where it applies

- **Live prototype briefs** (`/prototype/*`) — the primary target.
- The **verified brief** (`/verified-brief`) — already implemented; becomes the
  reference design.
- The **real engine brief** (`ExecutiveDecisionBrief`) — extend the existing
  `EvidenceCard` rather than build a second component.

## 4. Reuse (no new systems)

- Extend the existing `EvidenceCard` + `OutcomeRange` rendering.
- Consume the engine's Phase-2 fields (`comparability`, `outcome_attribution`,
  `supports_direct_outcome`) — do not re-derive in the web.

## 5. Sequence

1. Generalize the `/verified-brief` evidence card into a shared component.
2. Add citations to the live prototype brief's impact section.
3. Extend the real `ExecutiveDecisionBrief` evidence cards.
4. Add the claim-type labels to every evidence-derived number.

## 6. Acceptance criteria

- Every evidence-derived number in a production brief has either a citation or an
  explicit label (illustrative/assumption/insufficient).
- A `context only` or `vendor-reported` record never renders as a verified
  finding.
- Engine output and UI agree exactly (no web-side re-derivation).
- Automated test: no claim renders as verified unless the engine's
  `supports_direct_outcome` is true.

## 7. Dependencies

- Phase 2 engine fields (deployed).
- Plan A category audit (to know which briefs have real evidence to cite).

## 8. Out of scope

- New product features beyond provenance/calculation display.
- Any change to verification or comparability thresholds.
