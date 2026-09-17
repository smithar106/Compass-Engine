# Category Audit — Which Prototype Problem Has the Strongest Direct Evidence?

**Date:** 2026-08-24
**Scope:** the existing 54,277-record library, audited across all 10 prototype
problems.
**Question:** which category has the strongest **directly relevant, primary-source**
evidence (not which has the most records).

---

## 1. Method

For each prototype problem's canonical workflow(s), counted records and filtered
to:
- **primary source** (SEC filing / annual report / earnings call / government /
  academic / independent) — excluding vendor case studies;
- **quantified metric** present;
- then **read the source context** to judge whether the record documents an actual
  implementation and whether it attributes the outcome to the intervention.

## 2. Coverage matrix

| Prototype problem | Records | Primary source | Primary + metric |
|---|---|---|---|
| misrouted-support (ticketing/call_routing) | 1,207 | 12 | 9 |
| repetitive-reporting (analytics/financial reporting) | 1,139 | 2 | 1 |
| late-escalations (relationship/customer journey) | 497 | 1 | 0 |
| manual-invoice-processing (invoice/AP) | 481 | 8 | 7 |
| slow-employee-ramp (onboarding/learning) | 471 | 3 | 1 |
| sales-handoff-rework (order processing) | 281 | 8 | 6 |
| trapped-knowledge (knowledge/document mgmt) | 276 | 5 | 5 |
| manual-forecasting (forecasting) | 256 | 1 | 1 |
| hard-to-find-information (self-service) | 153 | 1 | 1 |
| slow-customer-onboarding (onboarding) | 142 | 0 | 0 |

**Record volume ≠ evidence quality.** `misrouted-support` has the most records and
the most primary-source records, but most are unrelated (acquisitions,
restructuring, financial results).

## 3. Candidate assessment (read in context)

| Category | Candidate | Actual implementation? | Intervention → outcome attributed? | Verdict |
|---|---|---|---|---|
| **knowledge/document** | **Exela / SourceHOV** (SEC) | **Yes** | **Yes — explicit** | **Strong direct candidate** |
| knowledge/document | ManpowerGroup (SEC) | Partly (DDI program) | No (metrics are business mix) | Weak |
| knowledge/document | Mitek ×4, Captiva (SEC) | No — **vendors** describing products | No | Context only |
| misrouted-support | CVS / IBM Watson (SEC exhibit) | Yes (AI assistant) | Volume reported ("10M calls"); vendor (IBM) | Vendor-reported |
| misrouted-support | Express Scripts (SEC) | Broad tech investment | No (SG&A/operating income, company-wide) | Indirect |
| sales-handoff | Sysorex (SEC) | Yes (systems automation) | **No** — attributed to business growth | Unattributed |
| sales-handoff | Armstrong (SEC) | Goal ("shorten design-to-order…") | No — a target, not a result | Not an outcome |
| invoice | (all 9 primary) | No — provider scale / adjacent | No | Indirect/not-relevant (see prior audit) |

### The strongest single record (verified against source)

**Exela / SourceHOV** — SEC filing:
> "Revenue per head for SourceHOV has more than tripled ($18,000 per FTE in 2007
> to $56,000 per FTE in 2016) with headcount being reduced by over 1,000 FTEs
> **as a result of the adoption of its technology-focused strategy**."

This is a documented implementation with a quantified outcome **and explicit
attribution** — the only candidate of its kind found in the audit. Category:
document/knowledge processing automation.

## 4. Finding

- **Strongest category: knowledge/document processing automation
  (`trapped-knowledge`)** — it is the only category with a verified,
  explicitly-attributed direct-implementation record (Exela).
- Every other category's candidates are **vendor-reported**, **company-wide /
  unattributed**, or **goals rather than results**.
- **No category currently has a 5–10 record verified cohort.** The best
  (`trapped-knowledge`) has ~1 strong record plus vendor context.

## 5. Recommendation

1. **Target `trapped-knowledge` (document/knowledge processing automation)** for
   the acquisition pipeline — it has the strongest seed (Exela) and a coherent,
   commercially relevant theme (intelligent document processing, knowledge
   automation).
2. **Do not pursue invoice processing further** — confirmed 0 direct
   implementation records (prior audit).
3. **Acquire 5–10 direct-implementation records** for document/knowledge
   automation via EDGAR full-text (OCR/document-automation programs with
   quantified outcomes), government evaluations, and academic studies.
4. **Label vendor records (Mitek, Captiva) as vendor-reported context** — never
   verified direct evidence.
5. Re-present the brief for `trapped-knowledge` once a verified cohort exists.

## 6. Caveats

- The audit is a first pass over automated extraction; the Exela record was
  manually verified against its source, but the remaining candidates were assessed
  from extracted passages and should be re-checked before use.
- "Explicit attribution" here means the source states the intervention caused the
  outcome; it does not establish rigorous causal identification.
