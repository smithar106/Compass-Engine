# Compass Evidence Pipeline — Architecture Assessment & Implementation Plan

**Date:** 2026-08-24
**Author:** Engineering (agent-assisted)
**Status:** ASSESSMENT ONLY — no production data modified, nothing deployed.
**Scope:** Compass-Engine (evidence pipeline, DB, recommendation engine) + Compass-Web (decision brief UI).

> Note: a prior turn produced an uncommitted, **undeployed** local fix to
> `compass_collector/api/service.py` (named-company negative claims) plus
> `docs/named_company_risk_audit.md`. It is not in production. This document
> treats it as a proposed P0 change, not a shipped one.

---

## 1. Architecture map

```
COLLECT          compass_collector/scraper + source_registry
   ↓             (SEC filings, vendor case studies, gov audits, academic)
EXTRACT          scripts/06–30 (LLM extraction) → intervention_records
   ↓             fields: organization, problem, intervention, outcome, risks,
   ↓             implementation detail, provenance (sparse)
CLASSIFY         analysis/evidence_tier.py        → gold|decision_grade|supporting|rejected
   ↓             organization/workflow_taxonomy.py → canonical slugs
   ↓             organization/taxonomy.py          → canonical industry
STORE            data/collector_v3.db (SQLite)
   ↓             intervention_records, metric_records, passage_records,
   ↓             documents, quality_flags, duplicate_relationships, source_registry
GOVERN (partial) publication_status: staging|published|quarantined|rejected
   ↓             verification_status: legacy|source_authentic|document_verified|claim_verified|rejected
RETRIEVE         analysis/retrieval.py + candidate_retrieval.py
   ↓             (workflow taxonomy relations + similarity scoring)
RECOMMEND        api/service.py run_recommendation → RecommendationResponse
   ↓             OutcomeRange carries source_record_ids + calculation_method
PRESENT          Compass-Web:
                 - ExecutiveDecisionBrief.tsx (real, engine-backed) — has source links
                 - CompassDecision.tsx (prototype) — NO citations
VERIFY (library) Compass-Web lib: strict-verify.ts, governance.ts, quarantine.ts,
                 evidence-factory.ts  → **test-only, never enforced in production**
```

### Data reality (production `/api/metadata`, 2026-08-24)

| Metric | Value |
|---|---|
| `published_records` | 54,277 |
| `legacy_published_records` (verification_status = `legacy`) | 54,266 |
| `verified_published_records` (verification_status = `claim_verified`) | **11** |
| `gold` | 37 |
| `decision_grade` | 339 |
| `supporting` | 53,901 |
| `unique_organizations` | 3,721 |

Local DB structural facts (repo snapshot, 51,198 records):

| Fact | Count |
|---|---|
| Records with a resolvable source URL (via `documents`) | 46,931 |
| `passage_records` (verbatim source excerpts) | **345** |
| `metric_records` with a quantified change | 8,974 |
| `implementation_provenance` NULL | 45,958 (90%) |
| `outcome_provenance` NULL | 45,971 (90%) |
| `source_type` NULL | 50,325 (98%) |
| `evidence_level` NULL | 45,958 (90%) |

**The gap:** ~92% of records have a document URL, but verification/provenance
metadata is populated for only ~10%, verbatim evidence excerpts exist for
~0.7% of records, and only **11 records are `claim_verified`** in production.

---

## 2. Findings

### 2.1 Unsupported claims

| # | Claim | Where | Problem | Severity |
|---|---|---|---|---|
| U1 | "Some comparable implementations (Finastra, Tetra Pak) showed weaker results or encountered challenges" | Engine `_build_risks` → prototype brief | Names real companies in a negative context based **only on evidence tier** ("supporting"/"bronze" = documentation completeness, not results). 0/3 Finastra records have a source; Tetra Pak's linked source (UiPath case study) reports **success** — the claim is contradicted by its own source. | **CRITICAL** |
| U2 | "Built from 10,000+ **verified** implementation records" | Homepage `HeroTrustLine`, `EvidenceStats`, marketing | Production `verified_published_records` = **11**. "Verified" overstates the corpus by ~3 orders of magnitude. | **HIGH** |
| U3 | "83% reduction in processing time" (and peers) | Prototype brief Impact section | Number derived from comparable metrics but shown with **no source, no sample size, no trace**. Indistinguishable from a fabricated figure. | **HIGH** |
| U4 | "Moderate confidence based on 3 comparable implementations with 3 gold/decision-grade sources" | Prior prototype version (now removed) | Exposed internal evidence mechanics as if they were a finding; also presented tier counts as confidence. | MEDIUM (removed) |

### 2.2 Missing source references

| # | Surface | Finding |
|---|---|---|
| S1 | Prototype brief (`CompassDecision.tsx`) | **Zero citations.** Impact numbers, risks, and timeline have no source reference at all. |
| S2 | Real brief (`ExecutiveDecisionBrief.tsx`) | Renders a source link **only when `source_url` is present**. When absent, it still shows a badge ("Company Disclosure") **without a link** — implying provenance that isn't there. |
| S3 | Engine `passage_records` | Only **345** verbatim excerpts for 51K records; most claims have no stored supporting passage to cite. |
| S4 | `verification_status` label | `legacy` (54,266 records) is rendered/treated as usable evidence without surfacing that it is unverified. |

### 2.3 Inconsistent verification statuses

| # | Finding |
|---|---|
| V1 | Two parallel verification models exist: engine columns (`publication_status`, `verification_status`) and a richer Compass-Web library (`strict-verify.ts` 3-state: `source_authentic`/`document_verified`/`claim_verified`). **They are not reconciled.** |
| V2 | The Compass-Web governance/strict-verify/quarantine/evidence-factory modules are imported **only by tests** — never enforced on ingest, retrieval, or presentation. |
| V3 | `evidence_tier` (gold/decision_grade/supporting) is derived at read time by `classify_evidence_tier`, but `evidence_level` is stored and NULL for 90% — stored and derived values can disagree. |
| V4 | `verification_status` defaults to `legacy`; nothing prevents a `legacy` record from appearing as evidence in a brief. |

### 2.4 Untraceable recommendations

| # | Finding |
|---|---|
| T1 | `OutcomeRange` **does** carry `source_record_ids`, `calculation_method`, `sample_size`, and tier counts — good infrastructure — but these are **not surfaced** in the brief UI. |
| T2 | Impact estimates (`annual_savings`, `annual_hours_returned`) carry `basis` / `missing_inputs` in the engine but the brief shows only the headline number. |
| T3 | The prototype's impact numbers are assembled in `engine-mapper.ts` from `normalized_metrics` with no record-level trace retained for display. |
| T4 | Named risk statements carry a `source` field set to the literal string `"evidence"` — not a record id or URL. |

---

## 3. Proposed smallest implementation

Design principle: **reuse the infrastructure that already exists** (engine
`verification_status`, `OutcomeRange.source_record_ids`, Compass-Web
`strict-verify.ts`) rather than build a new system. Keep changes additive and
fail-closed.

### 3.1 Record-level provenance & verification status

- **Reuse** the existing `verification_status` enum
  (`legacy | source_authentic | document_verified | claim_verified | rejected`)
  and `publication_status`. Do **not** add a new field.
- Add a **single derived accessor** used everywhere:
  `record_claim_status(record, metrics, passages) -> {status, has_source_url,
  has_passage, source_url, source_title}` in the engine, so presentation never
  re-derives verification ad hoc.
- Backfill: leave existing rows as `legacy` (no fabricated upgrades). Compute a
  `verified` flag **only** when the Compass-Web `strict-verify` bar is met
  (trusted host + preserved content + passage present + metric supported).

### 3.2 Claim-level citations in decision briefs

- Extend the engine's `ComparableEvidence` payload (already carries
  `source_url`, `source_title`, `publication_date`, `supporting_passage`,
  `verification_status`) and **surface** those fields in the brief.
- In `CompassDecision.tsx`, attach a citation chip to each evidence-derived
  number/claim: `{source name} · {date} · ↗` linking to `source_url`; if no
  source, render **no chip** and mark the value `illustrative` (see 3.4).
- Reuse the existing `EvidenceCard` pattern from `ExecutiveDecisionBrief.tsx`
  (already renders `sourceUrl` + type badge) — do not build a second one.

### 3.3 Traceable calculations & assumptions

- Surface the fields the engine already computes:
  `OutcomeRange.source_record_ids`, `sample_size`, `calculation_method`,
  `direction`, tier counts; and `ImpactEstimate.basis` / `missing_inputs`.
- Add a single "How this was calculated" disclosure per impact metric showing
  method + N + source record ids (ids can link to a record view).

### 3.4 Fail-closed rule (the core requirement)

Add one gate function, enforced at the **presentation boundary** (and ideally
in the API response):

```
is_presentable_as_verified(claim) :=
    claim.has_source_url
 AND claim.verification_status in {source_authentic, document_verified, claim_verified}
 AND (for quantitative claims) claim.supporting_passage or claim.source_record_ids present
```

- If false → the claim **must not** render as a factual/verified statement.
  It renders as `illustrative` (explicitly labeled) or is omitted.
- Applies to: impact numbers, named risks, named organizations, vendor
  recommendations, timelines.
- **Named real companies may never appear in a negative/comparative context
  unless `is_presentable_as_verified` holds for that specific characterization**
  (per the named-company audit).

### 3.5 Automated tests for evidence integrity

- Engine (pytest): fail-closed gate unit tests; "no named company without a
  source in a negative context" invariant over the risk/counterevidence
  builders; `OutcomeRange` traceability (every range has ≥1 `source_record_id`
  or is marked illustrative).
- Web (vitest): a brief-level test asserting **no evidence-derived number
  renders without a citation or an `illustrative` label**; a test that a
  `legacy`-verification record never renders as "verified".
- CI: add the named-company invariant as a regression test (the audit's rule,
  encoded).

---

## 4. Prioritized implementation plan

| Pri | Item | Effort | Risk | Blocks |
|---|---|---|---|---|
| **P0** | Named-company negative claims: genericize (already drafted locally) + deploy | S | Low | Any public use |
| **P1** | Fail-closed gate `is_presentable_as_verified` + wire into brief rendering | M | Med | P2, P3 |
| **P2** | Claim-level citations in briefs (surface existing `source_url`/`source_title`) | M | Low | — |
| **P3** | Traceability disclosure (source_record_ids, method, sample size, basis) | M | Low | — |
| **P4** | Reconcile engine `verification_status` with Compass-Web `strict-verify` 3-state | M | Med | P1 |
| **P5** | Evidence-integrity tests + CI invariant | S | Low | — |
| **P6** | Copy reconciliation: "10,000+ verified" → precise verified/classified/raw counts | S | Low | P1 |

**Recommended sequence:** P0 → P1 → P2 → P5 (tests lock the invariant) → P3 →
P6 → P4. P0 is independent and urgent; P1 is the architectural keystone.

---

## 5. Migration risks

| Risk | Detail | Mitigation |
|---|---|---|
| **Over-claiming "verified"** | Backfilling `verification_status` upward would fabricate verification. | Never upgrade status automatically; only `strict-verify`-passing records may become `claim_verified`. Leave the rest `legacy`. |
| **Thin verified set** | Only 11 records are `claim_verified`; a fail-closed gate will make most briefs show "illustrative" or "insufficient evidence". | This is the **correct** behavior and matches "make insufficiency a feature." Communicate it; expand the verified set deliberately, not by lowering the bar. |
| **Two verification models drift** | Engine columns vs Compass-Web library. | Make the engine the single source of truth; have the web library consume engine status, not re-derive. |
| **Sparse provenance fields** | 90% NULL; a gate keyed on provenance will hide most records. | Gate on the fields that exist (`source_url` present for 92%) + require passage/verification for *verified* claims only. Two tiers: "sourced" vs "verified". |
| **Corrupt JSON rows** | Legacy rows break SQLAlchemy JSON deserialization (already observed in production). | Continue the raw-SQL/defensive-load pattern; add a data-quality check. |
| **DB is LFS-tracked** | Local runs can rewrite the tracked DB (observed). | Keep DB writes out of commits; verify pointer unchanged before push. |
| **Copy changes affect deck + site** | Numbers must match across surfaces. | Single counts endpoint; P6 only after P1. |

---

## 6. Acceptance criteria

**P0 (named-company)**
- [ ] No brief, for any of the 10 problems, names a real company in a negative/comparative context.
- [ ] A regression test asserts no organization name appears in risk/counterevidence text unless a linked source supports it.

**P1 (fail-closed)**
- [ ] Any evidence-derived claim without `source_url` + verified status renders as `illustrative` or is omitted — never as a verified fact.
- [ ] A unit test proves a `legacy`-status record cannot render as "verified".

**P2 (citations)**
- [ ] Every impact number in a brief shows either a clickable source citation (name + date + link) or an explicit `illustrative` label.
- [ ] No badge is shown that implies a source when `source_url` is absent.

**P3 (traceability)**
- [ ] Each quantitative impact metric exposes its calculation method, sample size, and ≥1 source record id (or is labeled illustrative).

**P4 (reconciliation)**
- [ ] Engine and web agree on a single `verification_status` taxonomy; the web does not re-derive it.

**P5 (tests)**
- [ ] Evidence-integrity tests run in CI and fail the build on violation.

**P6 (copy)**
- [ ] Every public evidence-count claim matches `/api/metadata` and uses precise language (e.g. "X sourced records, Y claim-verified"), consistent across homepage, how-it-works, product, deck, and brief.

---

## 7. What is NOT proposed

- No embeddings/ML, no schema rewrite, no new datastore.
- No automatic promotion of records to "verified".
- No fabricated sources, verification results, or counts.
- No change to production data or deploys without approval.
