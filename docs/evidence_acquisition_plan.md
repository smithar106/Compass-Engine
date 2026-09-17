# Plan A — Evidence Acquisition Strategy (for approval)

**Date:** 2026-08-24
**Status:** PLAN ONLY — no implementation.
**Context:** the acquisition audit found 0 suitable direct-implementation
candidates for invoice automation in the 54,277-record library
(`docs/evidence_acquisition_report.md`).

---

## The structural problem

The current collection process is optimized for finding **business information**,
not for documenting **intervention → outcome relationships**. A larger library
does not fix this; a different acquisition schema does.

## 1. New evidence acquisition schema

Every acquired record must capture:

| Field | What Compass needs |
|---|---|
| Organization | Who implemented the change? |
| Problem | What operational problem existed? |
| Intervention | What specifically changed? |
| Baseline | What was performance before? |
| Outcome | What happened afterward? |
| Attribution | What supports linking the change to the result? |
| Context | Industry, scale, timeframe |
| Source | Where is the evidence documented? |
| Limitations | What remains uncertain? |

This becomes the target shape for all future collection. Existing records that
lack baseline/attribution are usable as **context**, not as direct evidence.

## 2. Source classes (SEC is one class, not the only one)

| Class | Weight | Notes |
|---|---|---|
| Academic / peer-reviewed | High | Controlled comparisons, declared methods |
| Government evaluation / audit | High | Independent, public |
| Independent implementation study | High | Third-party documented |
| Public-company disclosure (SEC) | Medium | Accountable but company-wide, rarely intervention-specific |
| Vendor case study | **Vendor-reported** | Never labeled independently corroborated; context unless corroborated |

Rule: **vendor-reported** is a labeled provenance class, not an automatic
rejection. It may be shown as vendor-reported context and upgraded only if an
independent primary source corroborates the specific intervention→outcome link.

## 3. Sequence

1. **Category audit (first).** Audit the existing library across all **10
   prototype problems** to determine which category has the strongest directly
   relevant, primary-source coverage. Do **not** default to invoice processing.
   Deliverable: a per-category coverage matrix (direct / indirect / none).
2. **Target the winner.** Build a targeted acquisition pipeline for the category
   with the best source coverage **and** commercial relevance.
3. **Manually validate a small cohort.** 5–10 records passing the verified bar
   with `direct_implementation` + attribution reviewed by a human.
4. **Re-present the brief** for that category as implementation-backed.

## 4. Acquisition mechanics

- **EDGAR full-text search** (`efts.sec.gov/LATEST/search-index?q=…`) for
  disclosures naming an intervention with a quantified outcome.
- **Government/audit** sources (GAO, state auditors, NHS, gov.uk).
- **Academic** repositories (arXiv, DOI) for controlled studies.
- Per-candidate capture uses the schema in §1; comparability and attribution are
  **assigned by human review**, never inferred.

## 5. Acceptance criteria

- A per-category coverage matrix across all 10 problems.
- ≥1 category with ≥5 records that pass the verified bar with
  `direct_implementation` + explicit attribution.
- Every acquired record has a resolvable primary source + supporting passage.
- Vendor-reported records are labeled and never presented as independently
  corroborated.

## 6. Explicitly out of scope

- Ingesting vendor case studies as verified evidence.
- Auto-promoting comparability or attribution.
- Scaling the library before the schema and category audit are in place.
